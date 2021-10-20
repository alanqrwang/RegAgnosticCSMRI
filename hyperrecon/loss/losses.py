from . import loss_ops
import functools

REGISTERED_SUP_LOSSES = [
                          'ssim',
                          'watson-dft',
                          'l1',
                          'mse',
                          'dice',
                        ]
REGISTERED_UNSUP_LOSSES = [
                              'dc',
                              'mindc',
                              'tv',
                              'wave',
                              'shear',
                            ]


def compose_loss_seq(loss_list, forward_model, mask, device):
  """Compose loss list.

  Args:
    aug_list: List of tuples (aug_type, kwargs)
    mask: Under-sampling mask
    device: Cuda device
  """
  return [
    generate_loss_ops(loss_type, forward_model, mask, device)
    for loss_type in loss_list
  ]

def generate_loss_ops(loss_type, forward_model, mask, device):
  """Generate Loss Operators."""
  assert loss_type.lower() in REGISTERED_SUP_LOSSES + REGISTERED_UNSUP_LOSSES

  if loss_type.lower() == 'tv':
    tx_op = loss_ops.TotalVariation()
  elif loss_type.lower() == 'wave':
    tx_op = loss_ops.L1Wavelets(device)
  # elif loss_type.lower() == 'shear':
  #   tx_op = loss_ops.L1_Shearlets(mask.shape)
  elif loss_type.lower() == 'ssim':
    tx_op = loss_ops.SSIM()
  elif loss_type.lower() == 'watson-dft':
    tx_op = loss_ops.WatsonDFT(device)
  elif loss_type.lower() == 'dc':
    tx_op = loss_ops.DataConsistency(forward_model, mask)
  elif loss_type.lower() == 'mindc':
    tx_op = loss_ops.MinNormDataConsistency(forward_model, mask)
  elif loss_type.lower() == 'l1':
    tx_op = loss_ops.L1()
  elif loss_type.lower() == 'mse':
    tx_op = loss_ops.MSE()
  elif loss_type.lower() == 'dice':
    tx_op = loss_ops.DICE()
  else:
    raise NotImplementedError

  return functools.partial(tx_op)