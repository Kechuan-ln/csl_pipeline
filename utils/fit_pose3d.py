import numpy as np
import torch
from typing import List
from utils.constants import COCO_SKELETON, COCO_SKELETON_FLIP_PAIRS


def build_optimizer(parameters, optimizer_cfg):
    """Simple replacement for mmcv's build_optimizer function."""
    optimizer_type = optimizer_cfg['type']
    
    # Create kwargs without the 'type' key
    kwargs = {k: v for k, v in optimizer_cfg.items() if k != 'type'}
    
    if optimizer_type == 'LBFGS':
        return torch.optim.LBFGS(parameters.parameters(), **kwargs)
    elif optimizer_type == 'Adam':
        return torch.optim.Adam(parameters.parameters(), **kwargs)
    elif optimizer_type == 'SGD':
        return torch.optim.SGD(parameters.parameters(), **kwargs)
    elif optimizer_type == 'AdamW':
        return torch.optim.AdamW(parameters.parameters(), **kwargs)
    else:
        raise ValueError(f"Unsupported optimizer type: {optimizer_type}")



###----------------------------------------------------------------------------
class OptimizableParameters():
    """Collects parameters for optimization."""

    def __init__(self):
        self.opt_params = []
        return

    def set_param(self, param: torch.Tensor) -> None:
        """Set requires_grad and collect parameters for optimization.
        Args:
            fit_param: whether to optimize this body model parameter
            param: body model parameter
        Returns:
            None
        """
        param.requires_grad = True
        self.opt_params.append(param)
        return

    def parameters(self) -> List[torch.Tensor]:
        """Returns parameters. Compatible with mmcv's build_parameters()
        Returns:
            opt_params: a list of body model parameters for optimization
        """
        return self.opt_params


class SkeletonFit:
    def __init__(self, cfg, logger, global_iter, total_global_iters):
        self.cfg = cfg
        self.logger = logger
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.num_iter = cfg.FIT_POSE3D.NUM_ITERS
        self.num_epochs = cfg.FIT_POSE3D.NUM_EPOCHS
        self.ftol = cfg.FIT_POSE3D.FTOL
        self.optimizer = dict(type='LBFGS', max_iter=cfg.FIT_POSE3D.MAX_ITER, lr=cfg.FIT_POSE3D.LR, line_search_fn='strong_wolfe')
        
        self.init_pose_loss_weight = cfg.FIT_POSE3D.INIT_POSE_LOSS_WEIGHT
        self.limb_length_loss = cfg.FIT_POSE3D.LIMB_LENGTH_LOSS_WEIGHT
        self.symmetry_loss_weight = cfg.FIT_POSE3D.SYMMETRY_LOSS_WEIGHT
        self.temporal_loss_weight = cfg.FIT_POSE3D.TEMPORAL_LOSS_WEIGHT

        self.global_iter = global_iter
        self.total_global_iters = total_global_iters


    def __call__(self, poses, verbose=False):
        poses = poses[:, :, :3] ## drop the validity flag
        assert(poses.shape[1] == 17 and poses.shape[2] == 3)

        # if numpy poses, convert to tensor
        if isinstance(poses, np.ndarray):
            poses = torch.from_numpy(poses)
        

        poses = poses.to(self.device)
        init_poses = poses.clone()

        for i in range(self.num_epochs):
            self._optimize_stage(poses, init_poses=init_poses, epoch_idx=i, verbose=verbose)
        return poses

    def _optimize_stage(self, poses, init_poses, epoch_idx, verbose=False):
        parameters = OptimizableParameters()
        parameters.set_param(poses)
        optimizer = build_optimizer(parameters, self.optimizer)
        pre_loss = None

        for iter_idx in range(self.num_iter):
            def closure():
                optimizer.zero_grad()
                loss_dict = self.evaluate(poses, init_poses, iter_idx, epoch_idx, verbose=verbose)
                loss = loss_dict['total_loss']
                loss.backward()
                return loss
            
            loss = optimizer.step(closure)
            
            if iter_idx > 0 and pre_loss is not None and self.ftol > 0:
                loss_rel_change = self._compute_relative_change(pre_loss, loss.item())
                if loss_rel_change < self.ftol:
                    if verbose:
                        self.logger.info(f'[ftol={self.ftol}] Early stop at {iter_idx} iter!')
                    break
            pre_loss = loss.item()
        return

    def evaluate(self, poses, init_poses, iter_idx, epoch_idx, verbose=False):
        total_time = poses.shape[0]
        losses = {}

        ##----------compute limbs-----------------
        limb_lengths = {}
        for limb_name in COCO_SKELETON.keys():
            limb_lengths[limb_name] = self.get_limb_length(poses, COCO_SKELETON[limb_name]) # T x 1

        ##------------limb length loss---------------------
        limb_length_loss = 0
        for limb_name in COCO_SKELETON.keys():
            average_limb_length = limb_lengths[limb_name].mean()
            limb_length_loss += (torch.abs(limb_lengths[limb_name] - average_limb_length)).mean()
        losses['limb_length_loss'] = self.limb_length_loss*limb_length_loss

        ##------------symmetry limb loss---------------------
        symmetry_loss = 0
        for flip_pair in COCO_SKELETON_FLIP_PAIRS.keys():
            limb_pair_name = COCO_SKELETON_FLIP_PAIRS[flip_pair]
            symmetry_loss += (torch.abs(limb_lengths[limb_pair_name[0]] - limb_lengths[limb_pair_name[1]])).mean() # change from sum to mean
        losses['symmetry_loss'] = self.symmetry_loss_weight*symmetry_loss

        ##-------------initpose loss----------------------
        init_pose_loss = ((poses - init_poses)**2).sum(dim=2).mean()
        assert poses.shape == init_poses.shape, f"poses shape: {poses.shape}, init_poses shape: {init_poses.shape}"
        assert poses.shape[2] == 3 and poses.shape[1] == 17, f"poses shape: {poses.shape}, expected 17 keypoints with 3D coordinates"
        
        losses['init_pose_loss'] = self.init_pose_loss_weight*init_pose_loss

        ##--------------temporal loss------------------------------------
        temporal_loss = ((poses[1:, :, :] - poses[:-1, :, :])**2).sum(dim=2).mean()
        losses['temporal_loss'] = self.temporal_loss_weight * temporal_loss


        ##-------------------------------------------------------
        total_loss = 0
        for loss_name, loss in losses.items():
            total_loss = total_loss + loss
        losses['total_loss'] = total_loss


        ##-------------------------------------------------------
        if verbose:
            msg_to_print = f"Global {self.global_iter}/{self.total_global_iters}, Epoch {epoch_idx}/{self.num_epochs}, Iter {iter_idx}/{self.num_iter}, Losses:"
            for loss_name, loss in losses.items():
                loss_value = loss.item()
                msg_to_print += f"{loss_name[:-5]}={loss_value:.6f}, "

            self.logger.info(msg_to_print)

        return losses

    def get_limb_length(self, poses, idxs):
        diff = (poses[:, idxs[0]] - poses[:, idxs[1]])**2 ## T x 3
        assert diff.shape[1] == 3
        length = (torch.sqrt(diff.sum(dim=1))).view(-1, 1) ## [T, 1]
        return length

    def _compute_relative_change(self, pre_v, cur_v):
        """Compute relative loss change. If relative change is small enough, we
        can apply early stop to accelerate the optimization. (1) When one of
        the value is larger than 1, we calculate the relative change by diving
        their max value. (2) When both values are smaller than 1, it degrades
        to absolute change. Intuitively, if two values are small and close,
        dividing the difference by the max value may yield a large value.
        Args:
            pre_v: previous value
            cur_v: current value
        Returns:
            float: relative change
        """
        return np.abs(pre_v - cur_v) / max([np.abs(pre_v), np.abs(cur_v), 1])


###----------------------------------------------------------------------------
## poses = 716 x 17 x 4
def fit_pose3d(cfg, logger, poses_numpy, verbose=False):
    total_time = poses_numpy.shape[0]

    fitted_poses_numpy = poses_numpy.copy()
    for i in range(cfg.FIT_POSE3D.GLOBAL_ITERS):
        model = SkeletonFit(cfg, logger, i, cfg.FIT_POSE3D.GLOBAL_ITERS)
        poses = torch.from_numpy(fitted_poses_numpy.copy()).to(model.device)
        fitted_poses = model(poses, verbose=verbose)
        fitted_poses_numpy[:, :, :3] = fitted_poses.cpu().detach().numpy()

    return fitted_poses_numpy


