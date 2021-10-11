import torch
import random
from hyperrecon.util.train import BaseTrain
from hyperrecon.util.metric import bpsnr
from hyperrecon.loss import loss_ops
import time
from tqdm import tqdm
import pytorch_ssim
from hyperrecon.util import utils

class Uniform(BaseTrain):
  """Uniform."""

  def __init__(self, args):
    super(Uniform, self).__init__(args=args)

  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.'''
    return torch.FloatTensor(num_samples, self.num_hparams).uniform_(0, 1)

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)
    # self.val_hparams = torch.tensor([[0.,0.], [1.,1.]])
    # hparams = []
    # for i in np.linspace(0, 1, 50):
    #   for j in np.linspace(0, 1, 50):
    #     hparams.append([i, j])
    # self.test_hparams = torch.tensor(hparams).float()

class UniformConstant(BaseTrain):
  """UniformConstant."""

  def __init__(self, args):
    super(UniformConstant, self).__init__(args=args)
  
  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.'''
    cat = random.random()
    return torch.ones(num_samples, self.num_hparams) * cat

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)

class UniformDiversityPrior(BaseTrain):
  """UniformDiversityPrior."""

  def __init__(self, args):
    super(UniformDiversityPrior, self).__init__(args=args)
    if self.distance_type == 'l2':
      self.distance_metric = loss_ops.L2Loss()
    elif self.distance_type == 'ssim':
      self.distance_metric = pytorch_ssim.SSIM(size_average=False)
    elif self.distance_type == 'watson_dft':
      self.distance_metric = loss_ops.Watson_DFT('cuda:0')
    elif self.distance_type == 'lpf_l2':
      self.distance_metric = loss_ops.LPF_L2('cuda:0')
    elif self.distance_type == 'unet_enc_feat':
      self.distance_metric = loss_ops.UnetEncFeat()
  
  def set_monitor(self):
    self.list_of_monitor = [
      'learning_rate', 
      'time:train',
      'diversity_loss',
      'recon_loss'
    ]

  def sample_hparams(self, num_samples):
    '''Samples hyperparameters from distribution.'''
    return torch.FloatTensor(num_samples, self.num_hparams).uniform_(0, 1)
  
  def train_epoch(self):
    """Train for one epoch."""
    self.network.train()

    epoch_loss = 0
    epoch_samples = 0
    epoch_psnr = 0
    epoch_div_loss = 0
    epoch_recon_loss = 0

    start_time = time.time()
    for i, (targets, segs) in tqdm(enumerate(self.train_loader), total=self.num_steps_per_epoch):
      loss, psnr, batch_size, recon_loss, div_loss = self.train_step(targets, segs)
      epoch_loss += loss * batch_size
      epoch_psnr += psnr * batch_size
      epoch_samples += batch_size
      epoch_recon_loss += recon_loss * batch_size
      epoch_div_loss += div_loss * batch_size
      if i == self.num_steps_per_epoch:
        break
    self.scheduler.step()

    epoch_time = time.time() - start_time
    epoch_loss /= epoch_samples
    epoch_psnr /= epoch_samples
    epoch_recon_loss /= epoch_samples
    epoch_div_loss /= epoch_samples
    self.metrics['loss:train'].append(epoch_loss)
    self.metrics['psnr:train'].append(epoch_psnr)
    self.monitor['learning_rate'].append(self.scheduler.get_last_lr()[0])
    self.monitor['time:train'].append(epoch_time)
    self.monitor['diversity_loss'].append(epoch_div_loss)
    self.monitor['recon_loss'].append(epoch_recon_loss)

    print("train loss={:.6f}, train psnr={:.6f}, train time={:.6f}".format(
      epoch_loss, epoch_psnr, epoch_time))

  def train_step(self, targets, segs):
    '''Train for one step.'''
    targets, segs = targets.float().to(self.device), segs.float().to(self.device)
    batch_size = len(targets) * 2
    undersample_mask = self.mask_module(batch_size).to(self.device)
    targets = torch.cat((targets, targets), dim=0)
    segs = torch.cat((segs, segs), dim=0)
    measurements, measurements_ksp = self.forward_model.generate_measurement(targets, undersample_mask)
    self.optimizer.zero_grad()
    with torch.set_grad_enabled(True):
      hparams = self.sample_hparams(batch_size)
      coeffs = self.generate_coefficients(hparams)
      pred = self.inference(measurements, coeffs)

      loss, recon_loss, div_loss = self.compute_loss(pred, targets, measurements_ksp, segs, coeffs, is_training=True)
      loss = self.process_loss(loss)
      loss.backward()
      self.optimizer.step()
    psnr = bpsnr(targets, pred)
    return loss.cpu().detach().numpy(), psnr, batch_size // 2, \
      recon_loss.mean().cpu().detach().numpy(), div_loss.mean().cpu().detach().numpy()

  def compute_loss(self, pred, gt, y, seg, coeffs, is_training=False):
    '''Compute loss with diversity prior. 
    Batch size should be 2 * self.batch_size

    Args:
      pred: Predictions (2*bs, nch, n1, n2)
      gt: Ground truths (2*bs, nch, n1, n2)
      y: Under-sampled k-space (2*bs, nch, n1, n2)
      coeffs: Loss coefficients (2*bs, num_losses)

    Returns:
      loss: Per-sample loss (bs)
    '''
    bs, n_ch, n1, n2 = pred.shape
    assert len(self.losses) == coeffs.shape[1], 'loss and coeff mismatch'
    recon_loss = 0
    for i in range(len(self.losses)):
      l = self.losses[i]
      c = coeffs[:, i]
      per_loss_scale = self.per_loss_scale_constants[i]
      recon_loss += c / per_loss_scale * l(pred, gt, y=y, seg=seg)
    
    if is_training:
      # TODO: generalize to higher-order coefficients
      hparams = coeffs[:, 1]

      recon_loss = recon_loss[:self.batch_size] + recon_loss[self.batch_size:]
      lmbda = torch.abs(hparams[:self.batch_size] - hparams[self.batch_size:])

      if isinstance(self.distance_metric, (loss_ops.L2Loss, pytorch_ssim.SSIM, loss_ops.Watson_DFT, loss_ops.LPF_L2)):
        batch1 = utils.unit_rescale(pred[:self.batch_size])
        batch2 = utils.unit_rescale(pred[self.batch_size:])
        diversity_loss = 1/(n_ch*n1*n2) * self.distance_metric(batch1, batch2)
      elif isinstance(self.distance_metric, loss_ops.UnetEncFeat):
        diversity_loss = self.distance_metric(self.network.unet)

      total_loss = recon_loss - self.beta*lmbda*diversity_loss
      return total_loss, recon_loss, diversity_loss
    else:
      return recon_loss

  def set_eval_hparams(self):
    self.val_hparams = torch.tensor([0., 1.]).view(-1, 1)
    # self.test_hparams = torch.tensor([0., 0.25, 0.5, 0.75, 1.]).view(-1, 1)
    self.test_hparams = torch.tensor([0., 1.]).view(-1, 1)