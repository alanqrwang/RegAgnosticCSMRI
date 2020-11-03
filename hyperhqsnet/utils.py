import torch
import numpy as np
import myutils
# import parse

def path2config(path):
    parse_format = '/nfs02/users/aw847/models/HyperHQSNet/{prefix}_{recon_type}_{lr}_{batch_size}_{lmbda}_{K}_{reg_types}_{n_hidden}_{alpha_bound}_{beta_bound}_{topK}_{range_restrict}/{dataset}_{maskname}/{filename}'
            
    config = parse.parse(parse_format, path)
    assert (config is not None), '\n parse_format is %s \n path is %s' % (parse_format, path)
    return config

def add_bool_arg(parser, name, default=True):
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--' + name, dest=name, action='store_true')
    group.add_argument('--no_' + name, dest=name, action='store_false')
    parser.set_defaults(**{name:default})

def abs(arr):
    # Expects input of size (N, l, w, 2)
    assert arr.shape[-1] == 2
    return torch.norm(arr, dim=3)

def scale(y, y_zf):
    # print('ifft', torch.sum(y_zf))
    flat_yzf = torch.flatten(abs(y_zf), start_dim=1, end_dim=2)
    # print('flat_yzf', torch.sum(flat_yzf))
    max_val_per_batch, _ = torch.max(flat_yzf, dim=1, keepdim=True)
    # print('max_val', torch.sum(max_val_per_batch))
    y = y / max_val_per_batch.view(len(y), 1, 1, 1)
    y_zf = y_zf / max_val_per_batch.view(len(y), 1, 1, 1)
    return y, y_zf

def fft(x):
    return torch.fft(x, signal_ndim=2, normalized=True)

def ifft(x):
    return torch.ifft(x, signal_ndim=2, normalized=True)

def get_reg_coeff():
    # return 0.002, 0.005
    return 0.002

def get_lmbda():
    return 0

def get_K():
    return 5

def get_data(data_path, N=None):
    print('Loading from', data_path)
    xdata = np.load(data_path)
    assert len(xdata.shape) == 4
    print('data shapes:', xdata.shape)
    return xdata

def get_mask(maskname, centered=False):
    mask = np.load('/nfs02/users/aw847/data/Masks/poisson_disk_%s_256_256.npy' % maskname)
    if not centered:
        return np.fft.fftshift(mask)
    else:
        return mask

def normalize_recons(recons):
    recons = myutils.array.make_imshowable(recons)
    recons = myutils.array.normalize(recons)
    return recons

def get_test_gt(dataset):
    if dataset == 't1':
        gt_path = '/nfs02/users/aw847/data/brain/adrian/brain_test_normalized.npy'
    elif dataset == 't2':
        gt_path = '/nfs02/users/aw847/data/brain/IXI-T2/IXI-T2_test_normalized.npy'
    elif dataset == 'knee':
        gt_path = '/nfs02/users/aw847/data/knee/knee_test_normalized.npy'
    elif dataset == 'brats':
        gt_path = '/nfs02/users/aw847/data/brain/brats/brats_t1_test_normalized.npy'

    gt = get_data(gt_path)
    return gt

def get_test_xdata(dataset, maskname):
    if dataset == 't1':
        data_path = '/nfs02/users/aw847/data/brain/adrian/brain_test_normalized_{maskname}.npy'
    elif dataset == 't2':
        data_path = '/nfs02/users/aw847/data/brain/IXI-T2/IXI-T2_test_normalized_{maskname}.npy'
    elif dataset == 'knee':
        data_path = '/nfs02/users/aw847/data/knee/knee_test_normalized_{maskname}.npy'
    elif dataset == 'brats':
        data_path = '/nfs02/users/aw847/data/brain/brats/brats_t1_test_normalized_{maskname}.npy'

    data = get_data(data_path.format(maskname=maskname))
    return data

def get_train_gt(dataset):
    if dataset == 't1':
        gt_path = '/nfs02/users/aw847/data/brain/adrian/brain_train_normalized.npy'
    elif dataset == 't2':
        gt_path = '/nfs02/users/aw847/data/brain/IXI-T2/IXI-T2_train_normalized.npy'
    elif dataset == 'knee':
        gt_path = '/nfs02/users/aw847/data/knee/knee_train_normalized.npy'
    elif dataset == 'brats':
        gt_path = '/nfs02/users/aw847/data/brain/brats/brats_t1_train_normalized.npy'

    gt = get_data(gt_path)
    return gt

def get_train_xdata(dataset, maskname):
    if dataset == 't1':
        data_path = '/nfs02/users/aw847/data/brain/adrian/brain_train_normalized_{maskname}.npy'
    elif dataset == 't2':
        data_path = '/nfs02/users/aw847/data/brain/IXI-T2/IXI-T2_train_normalized_{maskname}.npy'
    elif dataset == 'knee':
        data_path = '/nfs02/users/aw847/data/knee/knee_train_normalized_{maskname}.npy'
    elif dataset == 'brats':
        data_path = '/nfs02/users/aw847/data/brain/brats/brats_t1_train_normalized_{maskname}.npy'

    data = get_data(data_path.format(maskname=maskname))
    return data


def sample_hyperparams(batch_size, num_hyperparams, alpha_bound, beta_bound, fixed=None):
    if num_hyperparams == 2:
        alpha = sample_alpha(batch_size, alpha_bound, fixed)
        beta = sample_alpha(batch_size, beta_bound, fixed)

        hyperparams = torch.cat([alpha, beta], dim=1)
    else:
        hyperparams = sample_alpha(batch_size, alpha_bound, fixed)
    return hyperparams

def sample_alpha(batch_size, bound, fixed=False):
    r1 = float(bound[0])
    r2 = float(bound[1])

    sample = ((r1 - r2) * torch.rand((batch_size, 1)) + r2)
    
    if fixed is True:
        multinomial_p = torch.tensor([1/3, 1/3, 1/3])
        sample = torch.multinomial(multinomial_p, batch_size, replacement=True).float()
        print(sample)
        sample[sample==0] = ((r1 - r2) * torch.rand(()) + r2)
        sample[sample==1] = r1
        sample[sample==2] = r2
        sample = sample.view(batch_size, 1)
    else:
        sample = ((r1 - r2) * torch.rand((batch_size, 1)) + r2)


    # Bernoulli
    # samples = torch.empty(batch_size, 1).fill_(0.5)
    # sample = torch.bernoulli(samples)
    # sample[sample==0] = r1
    # sample[sample==1] = r2

    # print('doing single hp per batch')
    # single = ((r1 - r2) * torch.rand(()) + r2)
    # sample = torch.empty(batch_size, 1).fill_(single)
    return sample

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
