"""
Training loop for RegAgnosticCSMRI
For more details, please read:
    Alan Q. Wang, Adrian V. Dalca, and Mert R. Sabuncu. 
    "Regularization-Agnostic Compressed Sensing MRI with Hypernetworks" 
"""
from . import loss as losslayer
from . import utils, model, dataset, sampler, plot
import torch
from tqdm import tqdm
import numpy as np
import sys
import glob
import os

def trainer(xdata, gt_data, conf):
    """Training loop. 

    Handles model, optimizer, loss, and sampler generation.
    Handles data loading. Handles i/o and checkpoint loading.
        

    Parameters
    ----------
    xdata : numpy.array (N, img_height, img_width, 2)
        Dataset of under-sampled measurements
    gt_data : numpy.array (N, img_height, img_width, 2)
        Dataset of fully-sampled images
    conf : dict
        Miscellaneous parameters

    Returns
    ----------
    network : regagcsmri.UNet
        Main network and hypernetwork
    optimizer : torch.optim.Adam
        Adam optimizer
    epoch_loss : float
        Loss for this epoch
    """
    ###############  Dataset ########################
    trainset = dataset.Dataset(xdata[:int(len(xdata)*0.8)], gt_data[:int(len(gt_data)*0.8)])
    valset = dataset.Dataset(xdata[int(len(xdata)*0.8):], gt_data[int(len(gt_data)*0.8):])

    params = {'batch_size': conf['batch_size'],
         'shuffle': True,
         'num_workers': 4}
    dataloaders = {
        'train': torch.utils.data.DataLoader(trainset, **params),
        'val': torch.utils.data.DataLoader(valset, **params),
    }
    ##################################################

    ##### Model, Optimizer, Sampler, Loss ############
    num_hyperparams = len(conf['reg_types']) if conf['range_restrict'] else len(conf['reg_types']) + 1
    network = model.Unet(conf['device'], num_hyperparams=num_hyperparams, hyparch=conf['hyparch'], \
                nh=conf['unet_hidden']).to(conf['device'])

    optimizer = torch.optim.Adam(network.parameters(), lr=conf['lr'])
    if conf['force_lr'] is not None:
        for param_group in optimizer.param_groups:
            param_group['lr'] = conf['force_lr']

    hpsampler = sampler.HpSampler(num_hyperparams)
    criterion = losslayer.AmortizedLoss(conf['reg_types'], conf['range_restrict'], conf['sampling'], conf['device'], conf['mask'])
    ##################################################

    ############ Checkpoint Loading ##################
    if conf['load_checkpoint'] != 0:
        # pretrain_path = os.path.join(conf['filename'], 'model.{epoch:04d}.h5'.format(epoch=conf['load_checkpoint']))
        # network, optimizer = utils.load_checkpoint(network, pretrain_path, optimizer)
        pretrain_path = '/nfs02/users/aw847/models/HyperHQSNet/8fold_1e-05_42_[\'cap\', \'tv\']_64_None_True/model.5000.h5'
        network = utils.load_checkpoint(network, pretrain_path)
    ##################################################

    ############## Training loop #####################
    for epoch in range(conf['load_checkpoint']+1, conf['num_epochs']+1):
        print('\nEpoch %d/%d' % (epoch, conf['num_epochs']))
        if conf['force_lr'] is not None:
            print('Force learning rate:', conf['force_lr'])
        else:
            print('Learning rate:', conf['lr'])

        # Setting hyperparameter sampling parameters.
        # topK is number in mini-batch to backprop. If None, then uniform
        if conf['sampling'] == 'dhs' and epoch > conf['sample_schedule']:
            assert conf['topK'] is not None
            topK = conf['topK']
            print('DHS sampling')
        else:
            topK = None
            print('UHS sampling')

        # Loss scheduling. If activated, then first 100 epochs is trained 
        # as single reg function
        if len(conf['reg_types']) <= 2 and conf['range_restrict']:
            if epoch > conf['loss_schedule']:
                schedule = True
                print('Loss schedule: 2 regs')
            else:
                schedule = False
                print('Loss schedule: 1 reg')
        else:
            if conf['loss_schedule'] > 0:
                div = epoch // conf['loss_schedule']
                schedule = min(div, len(conf['reg_types']))
                print('%d losses' % schedule)
            else:
                schedule = len(conf['reg_types'])
                print('%d losses' % schedule)


        # Train
        network, optimizer, train_epoch_loss = train(network, dataloaders['train'], \
                criterion, optimizer, hpsampler, conf, topK, schedule)
        # Validate
        network, val_epoch_loss = validate(network, dataloaders['val'], criterion, hpsampler, conf, \
                topK, schedule)
        # Save checkpoints
        utils.save_checkpoint(epoch, network.state_dict(), optimizer.state_dict(), \
                train_epoch_loss, val_epoch_loss, conf['filename'], conf['log_interval'])
        utils.save_loss(epoch, train_epoch_loss, val_epoch_loss, conf['filename'])

def train(network, dataloader, criterion, optimizer, hpsampler, conf, topK, epoch):
    """Train for one epoch

        Parameters
        ----------
        network : hyperrrecon.UNet
            Main network and hypernetwork
        dataloader : torch.utils.data.DataLoader
            Training set dataloader
        optimizer : torch.optim.Adam
            Adam optimizer
        hpsampler : hyperrecon.HpSampler
            Hyperparameter sampler
        conf : dict
            Miscellaneous parameters
        topK : int or None
            K for DHS sampling
        epoch : int
            Current training epoch

        Returns
        ----------
        network : hyperrecon.UNet
            Main network and hypernetwork
        optimizer : torch.optim.Adam
            Adam optimizer
        epoch_loss : float
            Loss for this epoch
    """
    network.train()

    epoch_loss = 0
    epoch_samples = 0

    for batch_idx, (y, gt) in tqdm(enumerate(dataloader), total=len(dataloader)):
        y = y.float().to(conf['device'])
        gt = gt.float().to(conf['device'])

        optimizer.zero_grad()
        with torch.set_grad_enabled(True):
            zf = utils.ifft(y)
            y, zf = utils.scale(y, zf)

            hyperparams = hpsampler.sample(len(y)).to(conf['device'])

            recon, cap_reg = network(zf, y, hyperparams)
            loss, _, sort_hyperparams = criterion(recon, y, hyperparams, cap_reg, topK, epoch)

            loss.backward()
            optimizer.step()

            epoch_loss += loss.data.cpu().numpy()
        epoch_samples += len(y)
    epoch_loss /= epoch_samples
    return network, optimizer, epoch_loss

def validate(network, dataloader, criterion, hpsampler, conf, topK, epoch):
    """Validate for one epoch

        Parameters
        ----------
        network : hyperrecon.UNet
            Main network and hypernetwork
        dataloader : torch.utils.data.DataLoader
            Training set dataloader
        hpsampler : hyperrecon.HpSampler
            Hyperparameter sampler
        conf : dict
            Miscellaneous parameters
        topK : int or None
            K for DHS sampling
        epoch : int
            Current training epoch

        Returns
        ----------
        network : hyperrecon.UNet
            Main network and hypernetwork
        epoch_loss : float
            Loss for this epoch
    """
    network.eval()

    epoch_loss = 0
    epoch_samples = 0

    for batch_idx, (y, gt) in tqdm(enumerate(dataloader), total=len(dataloader)):
        y = y.float().to(conf['device'])
        gt = gt.float().to(conf['device'])

        with torch.set_grad_enabled(False):
            zf = utils.ifft(y)
            y, zf = utils.scale(y, zf)

            hyperparams = hpsampler.sample(len(y)).to(conf['device'])

            recon, cap_reg = network(zf, y, hyperparams)
            loss, _, _ = criterion(recon, y, hyperparams, cap_reg, topK, epoch)
                

            epoch_loss += loss.data.cpu().numpy()
        epoch_samples += len(y)
    epoch_loss /= epoch_samples
    return network, epoch_loss

def trajtrain(network, dataloader, trained_reconnet, criterion, optimizer, conf, lmbda, psnr_map=None, dc_map=None):
    losses = []

    for epoch in range(1, conf['num_epochs']+1):
        for batch_idx, (y, gt) in tqdm(enumerate(dataloader), total=len(dataloader)):
            if batch_idx > 100:
                break
            y = y.float().to(conf['device'])
            gt = gt.float().to(conf['device'])
            zf = utils.ifft(y)
            y, zf = utils.scale(y, zf)

            # Forward through trajectory net
            traj = torch.rand(conf['num_points']*conf['batch_size']).float().to(conf['device']).unsqueeze(1)

            optimizer.zero_grad()
            with torch.set_grad_enabled(True):
                out = network(traj)

            # Forward through recon net
            zf = torch.repeat_interleave(zf, conf['num_points'], dim=0)
            y = torch.repeat_interleave(y, conf['num_points'], dim=0)
            recons, cap_reg = trained_reconnet(zf, y, out)

            # Evaluate loss
            _, loss_dict, _ = criterion(recons, y, out, cap_reg, None, True)
            dc_losses = loss_dict['dc']
            recons = recons.view(conf['batch_size'], conf['num_points'], *recons.shape[1:])
            dc_losses = dc_losses.view(conf['batch_size'], conf['num_points'])
            loss = losslayer.trajloss(recons, dc_losses, lmbda, conf['device'], conf['loss_type'])
            
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
            plot.plot_traj_cp(network, conf['num_points'], losses, lmbda, conf['device'], psnr_map, dc_map, None)
            
            utils.save_loss(epoch, loss, 0, conf['save_path'])
            utils.save_checkpoint(epoch, network.state_dict(), optimizer.state_dict(), \
                    loss, 0, conf['save_path'], conf['log_interval'])
        
    return network
