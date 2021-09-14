import torch
import torch.nn as nn
import numpy as np
from hyperrecon.util.train import BaseTrain
from hyperrecon.model.unet import Unet
from hyperrecon.util import utils

class HypernetBaselineFitLayer(BaseTrain):
  """HypernetBaselineFitLayer."""

  def __init__(self, args):
    super(HypernetBaselineFitLayer, self).__init__(args=args)
    self.layer_idx = args.hypernet_baseline_fit_layer_idx

    model_path_0 = '/share/sablab/nfs02/users/aw847/models/HyperRecon/vert_bn_fixed/Sep_06/rate4_lr0.001_bs32_l1+ssim_hnet64_unet32_topKNone_restrictTrue_hp0.0/checkpoints/model.1024.h5'
    model_path_1 = '/share/sablab/nfs02/users/aw847/models/HyperRecon/vert_bn_fixed/Sep_06/rate4_lr0.001_bs32_l1+ssim_hnet64_unet32_topKNone_restrictTrue_hp1.0/checkpoints/model.1024.h5'

    trained_reconnet_0 = Unet(
        in_ch=2, 
        out_ch=1, 
        h_ch=32, 
        use_batchnorm=True
      ).to(args.device)
    trained_reconnet_1 = Unet(
        in_ch=2, 
        out_ch=1, 
        h_ch=32, 
        use_batchnorm=True
      ).to(args.device)

    trained_reconnet_0 = utils.load_checkpoint(trained_reconnet_0, model_path_0)
    trained_reconnet_1 = utils.load_checkpoint(trained_reconnet_1, model_path_1)
    trained_reconnet_0.eval()
    trained_reconnet_1.eval()
    for param in trained_reconnet_0.parameters():
      param.requires_grad = False
    for param in trained_reconnet_1.parameters():
      param.requires_grad = False

    conv_layers_0 = self.get_all_conv_layers(trained_reconnet_0, [])
    conv_layers_1 = self.get_all_conv_layers(trained_reconnet_1, [])

    self.base_conv_weights_0 = []
    self.base_conv_weights_1 = []
    for l0, l1 in zip(conv_layers_0, conv_layers_1):
      self.base_conv_weights_0.append(l0.weight)
      self.base_conv_weights_0.append(l0.bias)
      self.base_conv_weights_1.append(l1.weight)
      self.base_conv_weights_1.append(l1.bias)

  def train_epoch_begin(self):
      super().train_epoch_begin()
      print('Hypernet baseline fit per layer')
  
  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.'''
    return torch.bernoulli(torch.empty(num_samples, self.num_hparams).fill_(0.5))
    # return torch.ones((num_samples, self.num_hparams))

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([]).view(-1, 1)
    self.test_hparams = torch.tensor([]).view(-1, 1)


  def set_metrics(self):
    self.list_of_metrics = [
      'loss:train',
      'psnr:train',
    ]
    self.list_of_val_metrics = [
    ]
    self.list_of_test_metrics = [
    ]

  def get_all_conv_layers(self, network, all_layers):
    for layer in network.children():
      if type(layer) == nn.Conv2d: # if sequential layer, apply recursively to layers in sequential layer
        all_layers.append(layer)
      if list(layer.children()) != []: # if leaf node, add it to list
        all_layers = self.get_all_conv_layers(layer, all_layers)

    return all_layers

  def get_all_bn_layers(self, network, all_layers):
    for layer in network.children():
      if type(layer) == nn.BatchNorm2d: # if sequential layer, apply recursively to layers in sequential layer
        all_layers.append(layer)
      if list(layer.children()) != []: # if leaf node, add it to list
        all_layers = self.get_all_bn_layers(layer, all_layers)

    return all_layers

  def compute_loss(self, pred, gt, y, coeffs):
    all_conv_layers = utils.remove_sequential(self.network, [])

    # hyp_weights is list of outputs of hyperkernels and hyperbiases, which are of shape
    # (bs, *kernel_shape) and (bs, *bias_shape). Note that bs is the leading dimension
    # because the hyper layers produce a weight for each batch input.
    hyp_conv_weights = []
    for l in all_conv_layers:
      hyp_conv_weights.append(l.get_kernel())
      hyp_conv_weights.append(l.get_bias())

    assert len(hyp_conv_weights) == len(self.base_conv_weights_0)
    assert len(hyp_conv_weights) == len(self.base_conv_weights_1)

    # In contrast, self.base_weights_0 and 1 are lists of tensors of shape
    # (*kernel_shape) and (*bias_shape). So we don't need to index by
    # batch size to access them
    loss = 0
    for i, c in enumerate(coeffs):
      if c[1] == 0: # Compare against 0 model
        base_conv_weights = self.base_conv_weights_0
      else: # Compare against 1 model
        base_conv_weights = self.base_conv_weights_1
      
      w = hyp_conv_weights[self.layer_idx] 
      b = base_conv_weights[self.layer_idx]
      loss += (w[i].flatten() - b.flatten()).norm(p=2)
    return loss
  