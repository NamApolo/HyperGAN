from hypergan.util.gan_server import *
from hypergan.util.globals import *
from hypergan.util.ops import *

from tensorflow.python.framework import ops

import copy

import hyperchamber as hc

import hypergan as hg

from hypergan.discriminators import *
from hypergan.encoders import *
from hypergan.generators import *
from hypergan.loaders import *
from hypergan.regularizers import *
from hypergan.samplers import *
from hypergan.trainers import *
from hypergan.util import *

import importlib
import json
import numpy as np
import os
import sys
import tensorflow
import tensorflow as tf
import time
import uuid

class GAN:
    """ GANs (Generative Adversarial Networks) consist of a generator and discriminator(s)."""
    def __init__(self, config, graph, device='/gpu:0', graph_type='full'):
        """ Initialized a new GAN."""
        self.config=config
        self.device=device
        self.init_session(device)
        self.graph = self.create_graph(graph['x'], graph['y'], graph['f'], graph_type, device)

    def sample_to_file(self, name, sampler=grid_sampler.sample):
        sampler(name, self.sess, self.config)

    def create_graph(self, x, y, f, graph_type, device):
        self.graph = hg.graph.Graph(self.config)

        with tf.device(device):
            y=tf.cast(y,tf.int64)
            y=tf.one_hot(y, self.config['y_dims'], 1.0, 0.0)

            if graph_type == 'full':
                graph = self.graph.create(x,y,f)
            elif graph_type == 'generator':
                graph = self.graph.create_generator(x,y,f)
            else:
                raise Exception("Invalid graph type")

        return self.graph


    def init_session(self, device):
        # Initialize tensorflow
        with tf.device(device):
            self.sess = tf.Session(config=tf.ConfigProto())

    def train(self):
        return self.config['trainer.train'](self.sess, self.config)

    def save(self, save_file):
        saver = tf.train.Saver()
        saver.save(self.sess, save_file)

    def load_or_initialize_graph(self, save_file):
        save_file = os.path.expanduser(save_file)
        if os.path.isfile(save_file) or os.path.isfile(save_file + ".index" ):
            print(" |= Loading network from "+ save_file)
            ckpt = tf.train.get_checkpoint_state(os.path.expanduser('~/.hypergan/saves/'))
            if ckpt and ckpt.model_checkpoint_path:
                saver = tf.train.Saver()
                saver.restore(self.sess, save_file)
                loadedFromSave = True
                print("Model loaded")
            else:
                print("No checkpoint file found")
        else:
            print(" |= Initializing new network")
            with tf.device(self.device):
                init = tf.initialize_all_variables()
                self.sess.run(init)
