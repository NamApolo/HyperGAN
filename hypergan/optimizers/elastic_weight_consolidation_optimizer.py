from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import state_ops
from tensorflow.python.framework import ops
from tensorflow.python.training import optimizer
import tensorflow as tf
import hyperchamber as hc
import inspect

class ElasticWeightConsolidationOptimizer(optimizer.Optimizer):
  """ From https://arxiv.org/abs/1612.00796 """
  def __init__(self, learning_rate=0.001, loss=None, p=0.1, gan=None, config=None, use_locking=False, name="ElasticWeightConsolidationOptimizer", optimizer=None, rho=1, beta=1, gamma=1):
    super().__init__(use_locking, name)
    self.gan = gan
    self.config = config
    self._lr_t = learning_rate
    self.loss = loss

    self.optimizer = self.gan.create_optimizer(optimizer)
 
  def _prepare(self):
    super()._prepare()
    self.optimizer._prepare()

  def _create_slots(self, var_list):
    super()._create_slots(var_list)
    self.optimizer._create_slots(var_list)

  def _apply_dense(self, grad, var):
    return self.optimizer._apply_dense(grad, var)

  def apply_gradients(self, grads_and_vars, global_step=None, name=None):
    var_list = [v for _,v in grads_and_vars]
    d_vars = []
    g_vars = []
    all_grads = [ g for g, _ in grads_and_vars ]
    for grad,var in grads_and_vars:
        if var in self.gan.d_vars():
            d_vars += [var]
        elif var in self.gan.g_vars():
            g_vars += [var]
        else:
            raise("Couldn't find var in g_vars or d_vars")

    with ops.init_scope():
        f1 = [self._zeros_slot(v, "f", self._name) for v in var_list]

    with ops.init_scope():
        v1 = [self._get_or_make_slot(v, v, "v1", self._name) for v in var_list]
        if self.config.include_slots:
            for name in self.optimizer.get_slot_names():
                for var in self.optimizer.variables():
                    self._zeros_slot(var, "pm", "pm")
    self._prepare()

    f1 = [self.get_slot(v, "f") for v in var_list]
    v1 = [self.get_slot(v, "v1") for v in var_list]
    slots_list = []
    slots_vars = []
    if self.config.include_slots:
        for name in self.optimizer.get_slot_names():
            for var in self.optimizer.variables():
                slots_vars += [var]
                slots_list.append(self._zeros_slot(var, "pm", "pm"))

    current_vars = var_list + slots_vars
    tmp_vars = v1 + slots_list

    diff = [tf.square(v-t) for v,t in zip(current_vars, tmp_vars)]

    f_accum = [(self.config.f_decay or 0.95) * f + tf.square(g) for f, g in zip(f1, all_grads)]
    self.gan.add_metric('f1',tf.reduce_sum([tf.reduce_sum(f) for f in f1]))
    f_accum = [tf.where(tf.is_nan(_f), tf.zeros_like(_f), _f) for _f in f_accum]
    f_accum = [tf.where(tf.is_inf(_f), tf.zeros_like(_f), _f) for _f in f_accum]

    reg = [tf.multiply(f, d) for f,d in zip(f1, diff)]
    reg = [tf.where(tf.is_nan(_f), tf.zeros_like(_f), _f) for _f in reg]
    ewc_loss = (self.config.lam or 17.5)/2.0 * tf.reduce_sum([tf.reduce_sum(r) for r in reg])
    self.gan.add_metric('ewc',ewc_loss)

    save_weights = tf.group(*[tf.assign(w, v) for w,v in zip(tmp_vars, current_vars)]) # store variables

    if isinstance(self.loss, list):
        if self.config.add_ewc_loss_gradients:
            newloss = [ewc_loss, ewc_loss]
        else:
            newloss = [self.loss[0]+ewc_loss, self.loss[1]+ewc_loss]

        new_grads = tf.gradients(newloss[0], d_vars) + tf.gradients(newloss[1], g_vars)
        self.optimizer.loss = [ewc_loss+self.loss[0], ewc_loss+self.loss[1]]
    else:
        if self.config.add_ewc_loss_gradients:
            newloss = ewc_loss
        else:
            newloss = self.loss+ewc_loss

        new_grads = tf.gradients(newloss, current_vars)
        self.optimizer.loss =ewc_loss+self.loss

    if self.config.add_ewc_loss_gradients:
        new_grads = [_g+_ng for _g,_ng in zip(all_grads, new_grads)]

    step = self.optimizer.apply_gradients(list(zip(new_grads, current_vars)).copy(), global_step=global_step, name=name)

    store_f = tf.group(*[tf.assign(w, v) for w,v in zip(f1, f_accum)])
    with tf.get_default_graph().control_dependencies([store_f]):
        with tf.get_default_graph().control_dependencies([step]):
            with tf.get_default_graph().control_dependencies([save_weights]):
                return tf.no_op()

  def _apply_sparse(self, grad, var):
    raise NotImplementedError("Sparse gradient updates are not supported.")
  def variables(self):
      return super().variables() + self.optimizer.variables()
