import logging
import os
import numpy as np

import warnings
warnings.filterwarnings("ignore")


OK = '\033[92m'
WARNING = '\033[93m'
FAIL = '\033[91m'
END = '\033[0m'

PINK = '\033[95m'
BLUE = '\033[94m'
GREEN = OK
RED = FAIL
WHITE = END
YELLOW = WARNING

class ColorLogger():
    def __init__(self, log_dir, log_name='log.txt'):
        # set log
        self._logger = logging.getLogger(log_name)
        self._logger.setLevel(logging.INFO)
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, log_name)
        file_log = logging.FileHandler(log_file, mode='a')
        file_log.setLevel(logging.INFO)
        console_log = logging.StreamHandler()
        console_log.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s %(message)s",
            "%m-%d %H:%M:%S")
        console_formatter = logging.Formatter(
            "{}%(asctime)s{} %(message)s".format(GREEN, END),
            "%m-%d %H:%M:%S")
        file_log.setFormatter(file_formatter)
        console_log.setFormatter(console_formatter)
        self._logger.addHandler(file_log)
        self._logger.addHandler(console_log)

    def debug(self, msg):
        self._logger.debug(str(msg))

    def info(self, msg):
        self._logger.info(str(msg))

    def warning(self, msg):
        self._logger.warning(WARNING + 'WRN: ' + str(msg) + END)

    def critical(self, msg):
        self._logger.critical(RED + 'CRI: ' + str(msg) + END)

    def error(self, msg):
        self._logger.error(RED + 'ERR: ' + str(msg) + END)




class Summarizer():
    def __init__(self, dict_len):
        self.dict_length = dict_len

        # frame-wise error
        self.frame_mpjpe = np.zeros((self.dict_length), dtype=np.float32)-1.
        self.frame_mpjpe_pa = np.zeros((self.dict_length), dtype=np.float32)-1.

        # framew-wise output and gt
        self.frame_est_smpl = np.zeros((self.dict_length, 72+10+3))
        self.frame_joints3d_est = np.zeros((self.dict_length, 29, 3))
        self.frame_joints3d_gt = np.zeros((self.dict_length, 29, 3))
        self.frame_joints3d_valid = np.zeros((self.dict_length, 29), dtype=np.float32)

        #framew-wise path
        self.frame_path = ['']*self.dict_length

        # pointer
        self.frame_start_pt = 0


    def update(self, batch_mpjpe, batch_mpjpe_pa, batch_est_smpl, batch_joints3d_est, batch_joints3d_gt, batch_joints3d_valid, batch_path):
        batch_size = len(batch_mpjpe)
        
        self.frame_mpjpe[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_mpjpe
        self.frame_mpjpe_pa[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_mpjpe_pa

        self.frame_est_smpl[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_est_smpl
        self.frame_joints3d_est[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_joints3d_est
        
        self.frame_joints3d_gt[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_joints3d_gt
        self.frame_joints3d_valid[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_joints3d_valid
        
        self.frame_path[self.frame_start_pt:self.frame_start_pt+batch_size] = batch_path

        self.frame_start_pt += batch_size



    def summarize_and_save(self, path_output, logger):
        # report average error
        error_mpjpe = self.frame_mpjpe[self.frame_mpjpe>=0].mean()
        error_mpjpe_pa = self.frame_mpjpe_pa[self.frame_mpjpe_pa>=0].mean()
        logger.info(f"MPJPE: {error_mpjpe:.2f} mm, MPJPE_PA: {error_mpjpe_pa:.2f} mm")

        if path_output is None:
            return
        

        logger.info(f"Summarize and save to {path_output}")
        np.savez_compressed(path_output,
                            frame_mpjpe=self.frame_mpjpe,
                            frame_mpjpe_pa=self.frame_mpjpe_pa,
                            frame_est_smpl=self.frame_est_smpl,
                            frame_joints3d_est=self.frame_joints3d_est,
                            frame_joints3d_gt=self.frame_joints3d_gt,
                            frame_joints3d_valid=self.frame_joints3d_valid,
                            frame_path=self.frame_path,
                            mean_mpjpe=error_mpjpe,
                            mean_mpjpe_pa=error_mpjpe_pa)
