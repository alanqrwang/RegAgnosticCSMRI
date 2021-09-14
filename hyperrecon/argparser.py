import argparse
import json
import time
import os
from pprint import pprint


class Parser(argparse.ArgumentParser):
  def __init__(self):
    super(Parser, self).__init__(description='HyperRecon')
    # I/O parameters
    self.add_argument('-fp', '--filename_prefix', type=str,
              help='filename prefix', required=True)
    self.add_argument('--models_dir', default='/share/sablab/nfs02/users/aw847/models/HyperRecon/',
              type=str, help='directory to save models')
    self.add_argument('--data_path', default='/share/sablab/nfs02/users/aw847/data/brain/abide/',
              type=str, help='directory to load data')
    self.add_argument('--log_interval', type=int,
              default=25, help='Frequency of logs')
    self.add_argument('--load', type=str, default=None,
              help='Load checkpoint at .h5 path')
    self.add_argument('--cont', type=int, default=0,
              help='Load checkpoint at .h5 path')
    self.add_argument('--gpu_id', type=int, default=0,
              help='gpu id to train on')
    self.add_argument('--date', type=str, default=None,
              help='Override date')
    self.add_bool_arg('arr_dataset', default=False)
    self.add_argument('--num_train_subjects', type=int, default=50,
              help='Number of subjects to train on')
    self.add_argument('--num_val_subjects', type=int, default=5,
              help='Number of subjects to validate on')

    # Machine learning parameters
    self.add_argument('--image_dims', type=tuple, default=(160, 224),
              help='Image dimensions')
    self.add_argument('--lr', type=float, default=1e-3,
              help='Learning rate')
    self.add_argument('--force_lr', type=float,
              default=None, help='Learning rate')
    self.add_argument('--batch_size', type=int,
              default=32, help='Batch size')
    self.add_argument('--num_steps_per_epoch', type=int,
              default=256, help='Num steps per epoch')
    self.add_argument('--num_epochs', type=int, default=1024,
              help='Total training epochs')
    self.add_argument('--unet_hdim', type=int, default=32)
    self.add_argument('--hnet_hdim', type=int,
              help='Hypernetwork architecture', default=64)
    self.add_argument('--n_ch_out', type=int,
              help='Number of output channels of main network', default=1)
    self.add_argument('--scheduler_step_size', type=int,
              default=128, help='Step size for scheduler')
    self.add_argument('--scheduler_gamma', type=float,
              default=0.5, help='Multiplicative factor for scheduler')
    self.add_argument('--seed', type=int,
              default=0, help='Seed')
    self.add_bool_arg('use_batchnorm', default=True)
    self.add_argument('--optimizer_type', type=str, default='adam',
              choices=['sgd', 'adam'])

    # Model parameters
    self.add_argument('--topK', type=int, default=None)
    self.add_argument('--undersampling_rate', type=str, default='4p2',
              choices=['4', '8', '4p2', '8p2', '8p3', '16p2', '16p3'])
    self.add_argument('--mask_type', type=str, default='poisson',
              choices=['poisson', 'epi_horizontal', 'epi_vertical'])
    self.add_argument('--loss_list', choices=['dc', 'tv', 'cap', 'wave', 'shear', 'mse', 'l1', 'ssim', 'watson-dft'],
              nargs='+', type=str, help='<Required> Set flag', required=True)
    self.add_argument(
      '--method', choices=['uhs', 'dhs', 'baseline', 'uhs_anneal', 'predict', 'constant', 'binary', 'hypernet_baseline_fit', 'hypernet_baseline_fit_layer'], type=str, help='Training method', required=True)
    self.add_bool_arg('range_restrict')
    self.add_bool_arg('anneal', default=False)
    self.add_argument('--hyperparameters', type=float, default=None)

  def add_bool_arg(self, name, default=True):
    """Add boolean argument to argparse parser"""
    group = self.add_mutually_exclusive_group(required=False)
    group.add_argument('--' + name, dest=name, action='store_true')
    group.add_argument('--no_' + name, dest=name, action='store_false')
    self.set_defaults(**{name: default})

  def validate_args(self, args):
    if args.method == 'dhs':
      assert args.topK is not None, 'DHS sampling must set topK'
    if args.method in ['baseline', 'constant']:
      assert args.hyperparameters is not None, 'Baseline and constant must set hyperparameters'
    if args.range_restrict:
      assert len(
        args.loss_list) <= 3, 'Range restrict loss must have 3 or fewer loss functions'
    if args.mask_type == 'poisson':
      assert 'p' in args.undersampling_rate, 'Invalid undersampling rate for poisson'
    elif 'epi' in args.mask_type:
      assert 'p' not in args.undersampling_rate, 'Invalid undersampling rate for epi'

  def parse(self):
    args = self.parse_args()
    self.validate_args(args)
    if args.date is None:
      date = '{}'.format(time.strftime('%b_%d'))
    else:
      date = args.date

    def stringify_loss(str_loss_list):
      str = str_loss_list[0]
      for i in range(1, len(str_loss_list)):
        str += '+' + str_loss_list[i]
      return str

    args.run_dir = os.path.join(args.models_dir, args.filename_prefix, date,
                  'rate{rate}_lr{lr}_bs{batch_size}_{losses}_hnet{hnet_hdim}_unet{unet_hdim}_topK{topK}_restrict{range_restrict}_hp{hps}'.format(
                    rate=args.undersampling_rate,
                    lr=args.lr,
                    batch_size=args.batch_size,
                    losses=stringify_loss(args.loss_list),
                    hnet_hdim=args.hnet_hdim,
                    unet_hdim=args.unet_hdim,
                    range_restrict=args.range_restrict,
                    topK=args.topK,
                    hps=args.hyperparameters,
                  ))
    if not os.path.exists(args.run_dir):
      os.makedirs(args.run_dir)

    # Print args and save to file
    print('Arguments:')
    pprint(vars(args))
    with open(args.run_dir + "/args.txt", 'w') as args_file:
      json.dump(vars(args), args_file, indent=4)
    return args
