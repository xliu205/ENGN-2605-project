#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
# Written by feymanpriv

import init_path
import sys, os
import numpy as np
import cv2
import pickle
from scipy.io import savemat 

import torch
import torch.nn as nn
import torch.nn.functional as F

from core.config import cfg
import core.config as config
from core.model.resnet import ResNet, ResHead 
from core.model.resnet import GeneralizedMeanPoolingP
from core.model.dolg_model import DOLG

from process import preprocess
from revisitop.dataset import configdataset
from util import walkfile, l2_norm

""" common settings """
MODEL_WEIGHTS = './weights/r101_dolg_512.pyth'
INFER_DIR = './datasets/RevisitOP/Roxford5k/images'
SCALE_LIST = [0.3535, 0.5, 0.7071, 1.0, 1.4142]

test_dataset = 'roxford5k'
#test_dataset = 'rparis6k'
DATA_DIR = './revisitop'
data_cfg = configdataset(test_dataset, DATA_DIR)


def setup_model():
    model = DOLG()
    print(model)
    load_checkpoint(MODEL_WEIGHTS, model)
    if torch.cuda.is_available():
        model.cuda()
    model.eval()
    return model


def extract(img, model):
    globalfeature = None
    for s in SCALE_LIST:
        im = preprocess(img.copy(), s)
        input_data = np.asarray([im], dtype=np.float32)
        input_data = torch.from_numpy(input_data)
        if torch.cuda.is_available():
            input_data = input_data.cuda()
        global_feature = model(input_data)
        global_feature = F.normalize(global_feature, p=2, dim=1)
        if globalfeature is None:
            globalfeature = global_feature.cpu().detach().numpy()
        else:
            globalfeature += global_feature.cpu().detach().numpy()
    global_feature = globalfeature / len(SCALE_LIST)
    global_feature = l2_norm(global_feature)
    return global_feature


def main(spath):
    with torch.no_grad():
        model = setup_model()
        feadic = {}
        for index, imgfile in enumerate(walkfile(spath)):
            ext = os.path.splitext(imgfile)[-1]
            name = os.path.basename(imgfile).split('.')[0]
            if ext.lower() in ['.jpg', '.jpeg', '.bmp', '.png', '.pgm']:
                try:
                    im = cv2.imread(imgfile)
                    if name in data_cfg['qimlist']:
                        pos = data_cfg['qimlist'].index(name)
                        x1, y1, x2, y2 = map(int, data_cfg['gnd'][pos]['bbx'])
                        cropped_im = im[y1:y2, x1:x2] #crop query image
                        im = cropped_im
                    if index % 1000 == 0:
                        print(index, name, im.shape)
                    im = im.astype(np.float32, copy=False)
                    data = extract(im, model)
                    feadic[name] = data
                except:
                    print (name)
    with open("./output/rparis_R50_512_test5.pickle", "wb") as fout:   
        pickle.dump(feadic, fout, protocol=2)


def main_multicard(spath, cutno, total_num):
    """multi processes for extracting 1M distractors features"""
    with torch.no_grad():
        model = setup_model()
        feadic = {'X':[]}
        for index, imgfile in enumerate(walkfile(spath)):
            if index % total_num != cutno - 1:
                continue
            ext = os.path.splitext(imgfile)[-1]
            name = os.path.basename(imgfile)
            if index % 100 == 0:
                print(index, name)
            if ext.lower() in ['.jpg', '.jpeg', '.bmp', '.png', '.pgm']:
                im = cv2.imread(imgfile)
                try:
                    h, w = im.shape[:2]
                    im = im.astype(np.float32, copy=False)
                    data =  extract(im, model)
                    feadic['X'].append(data)
                except:
                    print (name)
                    continue
        toname='./features/1M/'+".mat"+'_%d' % cutno
        savemat(toname,feadic)


def load_checkpoint(checkpoint_file, model):
    """Loads the checkpoint from the given file."""
    err_str = "Checkpoint '{}' not found"
    assert os.path.exists(checkpoint_file), err_str.format(checkpoint_file)
    checkpoint = torch.load(checkpoint_file, map_location="cpu")
    try:
        state_dict = checkpoint["model_state"]
    except KeyError:
        state_dict = checkpoint
    # Account for the DDP wrapper in the multi-gpu setting
    ms = model
    model_dict = ms.state_dict()
    pretrained_dict = {k: v for k, v in state_dict.items() 
                       if k in model_dict and model_dict[k].size() == v.size()}
    if len(pretrained_dict) == len(state_dict):
        print('All params loaded')
    else:
        print('construct model total {} keys and pretrin model total {} keys.' \
               .format(len(model_dict), len(state_dict)))
        print('{} pretrain keys load successfully.'.format(len(pretrained_dict)))
        not_loaded_keys = [k for k in state_dict.keys() 
                                if k not in pretrained_dict.keys()]
        print(('%s, ' * (len(not_loaded_keys) - 1) + '%s') % tuple(not_loaded_keys))

    model_dict.update(pretrained_dict)
    ms.load_state_dict(model_dict)
    #ms.load_state_dict(checkpoint["model_state"])
    return checkpoint


if __name__ == '__main__':
    print(sys.argv)
    config.load_cfg_fom_args("Extract feature.")
    config.assert_and_infer_cfg()
    cfg.freeze()

    total_card = cfg.INFER.TOTAL_NUM
    assert total_card > 0, 'cfg.TOTAL_NUM should larger than 0. ~'
    assert cfg.INFER.CUT_NUM <= total_card, "cfg.CUT_NUM <= cfg.TOTAL_NUM. ~"
    if total_card == 1:
        main(INFER_DIR)
    else:
        main_multicard(INFER_DIR, cfg.INFER.CUT_NUM, cfg.INFER.TOTAL_NUM)
