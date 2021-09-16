import torch
import random
import numpy as np
from hyperrecon.util.train import BaseTrain

class Binary(BaseTrain):
  """Binary sampling for hypernetwork."""

  def __init__(self, args):
    super(Binary, self).__init__(args=args)

  def train_epoch_begin(self):
    super().train_epoch_begin()
    print('Binary Sampling')
  
  def sample_hparams(self, num_samples):
    return torch.bernoulli(torch.empty(num_samples, self.num_hparams).fill_(0.5))

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)

class BinaryConstantBatch(BaseTrain):
  """BinaryConstantBatch."""

  def __init__(self, args):
    super(BinaryConstantBatch, self).__init__(args=args)

  def train_epoch_begin(self):
      super().train_epoch_begin()
      print('Binary Constant Batches')
  
  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.'''
    if random.random() < 0.5:
      return torch.zeros(num_samples, self.num_hparams)
    else:
      return torch.ones(num_samples, self.num_hparams)

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)

class BinaryAnneal(BaseTrain):
  """BinaryAnneal.
  
  TODO: For now, expects that model weights are pretrained on binary constant batches.
  """

  def __init__(self, args):
    super(BinaryAnneal, self).__init__(args=args)
    self.p_min = 0.01
    self.p_max = 0.5
    self.epoch_of_p_max = self.num_epochs * self.fraction_train_max
    self.p = self.p_min

  def set_monitor(self):
    self.list_of_monitor = [
      'learning_rate', 
      'time:train',
      'p_value',
    ]

  def set_metrics(self):
    self.list_of_metrics = [
      'loss:train',
      'psnr:train',
    ]
    self.list_of_val_metrics = [
      'loss:val:' + self.stringify_list(l.tolist()) for l in self.val_hparams
    ] + [
      'psnr:val:' + self.stringify_list(l.tolist()) for l in self.val_hparams
    ]
    self.list_of_test_metrics = [
    ]

  def train_epoch_begin(self):
      super().train_epoch_begin()
      print('Binary Annealing')
      print('p-value:', self.p)
      self.monitor['p_value'].append(self.p)
  
  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.
    
    Linearly increase p from p_min to p_max.
    '''
    self.p = min((self.p_max - self.p_min) / self.epoch_of_p_max * self.epoch + self.p_min, self.p_max)
    if random.random() < 0.5:
      samples = torch.bernoulli(torch.empty(num_samples, self.num_hparams).fill_(self.p))
    else:
      samples = torch.bernoulli(torch.empty(num_samples, self.num_hparams).fill_(1-self.p))
    return samples

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)
  
