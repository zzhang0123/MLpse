import copy

import numpy as N
import scipy.linalg
import h5py
from core import mpiutil
import sys
    

class Likelihood:
    def __init__(self, data_path, covariance_class_obj, threshold = None):
        self.jpvec = None
        self.fpvec = None
        self.threshold = threshold
        self.CV = covariance_class_obj
        self.dim = len(self.CV.para_ind_list)
        self.nontrivial_mmode_list = self.CV.nontrivial_mmode_list
        self.local_ms = mpiutil.partition_list_mpi(self.nontrivial_mmode_list, method="alt")
        fdata = h5py.File(data_path, 'r')
        self.local_data_kl_m = N.array([fdata['vis'][m] for m in self.local_ms])
        fdata.close()
        self.mmode_count = len(self.nontrivial_mmode_list)
        parameters = self.CV.make_binning_power()
        self.parameter_model_values = [parameters[i] for i in self.CV.para_ind_list]
        self.local_cv_noise_kl = [self.CV.make_noise_covariance_kl_m(mi, threshold) for mi in self.local_ms]

    def __call__(self, pvec):
        if self.pvec is pvec:
            return
        else:
            self.pvec = pvec                
            fun = mpiutil.parallel_map(
                                       self.make_funs_mi, self.nontrivial_mmode_list, method="alt"
                                       )
            # Unpack into separate lists of the log-likelihood function, jacobian, and hessian
            return sum(list(fun))/self.mmode_count

    def make_covariance_kl_m(self, pvec, mi, threshold = None):
        local_mindex = self.local_ms.index(mi)
        # assert len(pvec)==self.nonzero_alpha_dim
        cv_mat = copy.deepcopy(self.local_cv_noise_kl[local_mindex])
        for i in range(self.CV.nonzero_alpha_dim):
            cv_mat += pvec[i]*self.CV.load_Q_kl_mi_param(mi,self.CV.para_ind_list[i])
        return cv_mat
            
    def filter_m_modes_2(self):
        m_list = []
        for mi in self.CV.nontrivial_mmode_list:
            if self.CV.kltrans.modes_m(mi)[0] is None:
                if mpiutil.rank0:
                    print("The m={} mode is null.".format(mi))
            else:
                m_list.append(mi)
        return m_list

    def make_funs_mi(self, mi):
        C = self.make_covariance_kl_m(self.pvec, mi, self.threshold)
        len = C.shape[0]
        local_mindex = self.local_ms.index(mi)
        vis_kl = self.local_data_kl_m[local_mindex, :len]
        v_column = N.matrix(vis_kl.reshape((-1, 1)))
        C_inv = scipy.linalg.inv(C)
        C_inv_D = C_inv @ v_column @ v_column.H
        # compute m-mode log-likelihood
        fun_mi = N.linalg.slogdet(C)[1] + N.trace(C_inv_D)
        return fun_mi.real
"""    
    def calculate_Errors(self):
        fun = mpiutil.parallel_map(self.Fisher_m, self.nontrivial_mmode_list, method="alt")
        return scipy.linalg.inv(sum(list(fun)))
    
    def Fisher_m(self, mi):
        local_mindex = self.local_ms.index(mi)
        Q_alpha_list = self.local_Q_alpha_m[local_mindex]
        C = self.CV.make_covariance_kl_m(self.parameter_model_values, mi, Q_alpha_list, self.threshold)
        # len = C.shape[0]
        C_inv = scipy.linalg.inv(C)
        hess_mi = N.empty((self.dim, self.dim), dtype='complex128')
        for i in range(self.dim):
            for j in range(i, self.dim):
                hess_mi[i, j] = hess_mi[j, i] = N.trace(C_inv @ Q_alpha_list[i] @ C_inv @ Q_alpha_list[j])
        return hess_mi.real
"""
    
class Likelihood_with_J_only(Likelihood):
    def __call__(self, pvec):
        if self.pvec is pvec:
            return
        else:
            self.fpvec = pvec
            self.jpvec = pvec
            Result = mpiutil.parallel_map(
                                          self.make_funs_and_jacs_mi, self.nontrivial_mmode_list, method="alt"
                                          )
            # Unpack into separate lists of the log-likelihood function, jacobian, and hessian
            fun, jac = list(zip(*Result))
            self.fun = sum(list(fun))/self.mmode_count
            self.jac = sum(list(jac))/self.mmode_count

    def fetch_function_value(self,pvec):
        if self.fpvec == pvec:
            return
        else:
            self.fpvec = pvec
            Result = mpiutil.parallel_map(
                self.make_funs_mi, self.nontrivial_mmode_list, method="alt"
            )
            self.fun = sum(Result)/self.mmode_count

    def make_funs_and_jacs_mi(self, mi):
        # Q_alpha_list = self.CV.load_Q_kl_list(mi)
        # C = self.CV.make_covariance_kl_m(self.pvec, mi, Q_alpha_list, self.threshold)
        C = self.make_covariance_kl_m(self.pvec, mi, self.threshold)
        len = C.shape[0]
        Identity = N.identity(len)
        local_mindex = self.local_ms.index(mi)
        vis_kl = self.local_data_kl_m[local_mindex, :len]
        v_column = N.matrix(vis_kl.reshape((-1, 1)))
        del vis_kl, len
        C_inv = scipy.linalg.inv(C)
        #C_inv = (C_inv + C_inv.conj().T)/2
        C_inv_D = C_inv @ v_column @ v_column.H
        del v_column
        # compute m-mode log-likelihood
        fun_mi = N.linalg.slogdet(C)[1] + N.trace(C_inv_D)
        
        # compute m-mode Jacobian
        aux = (Identity - C_inv_D) @ C_inv
        jac_mi = N.array([N.trace(self.CV.load_Q_kl_mi_param(mi,self.CV.para_ind_list[i]) @ aux)
                          for i in range(self.dim)]).reshape((self.dim,))
                
        return fun_mi.real, jac_mi.real
    
class Likelihood_with_J_H(Likelihood):

    def __call__(self, pvec):
        if self.pvec is pvec:
            return
        else:
            self.pvec = pvec                
            Result = mpiutil.parallel_map(
                                          self.make_funs_mi, self.nontrivial_mmode_list, method="alt"
                                          )
            # Unpack into separate lists of the log-likelihood function, jacobian, and hessian
            fun, jac, hess = list(zip(*Result))
            self.fun = sum(list(fun))/self.mmode_count
            self.jac = sum(list(jac))/self.mmode_count
            self.hess = sum(list(hess))/self.mmode_count
    
    def make_funs_mi(self, mi):
        Q_alpha_list = self.CV.load_Q_kl_list(mi)
        C = self.CV.make_covariance_kl_m(self.pvec, mi, Q_alpha_list, self.threshold)
        len = C.shape[0]
        Identity = N.identity(len)
        local_mindex = self.local_ms.index(mi)
        vis_kl = self.local_data_kl_m[local_mindex, :len]
        v_column = N.matrix(vis_kl.reshape((-1, 1)))
        Dmat = v_column @ v_column.H
        
        C_inv = scipy.linalg.inv(C)
        C_inv_D = C_inv @ Dmat
        
        # compute m-mode log-likelihood
        fun_mi = N.linalg.slogdet(C)[1] + N.trace(C_inv_D)
        
        # compute m-mode Jacobian
        aux = (Identity - C_inv_D) @ C_inv
        pd = []
        for i in range(self.dim):
            # pd.append(N.trace(C_inv @ Q_alpha[i] @ (1. - C_inv @ self.Dmat))) 
            # To save computing source, it can be simplified as
            pd.append(N.trace(Q_alpha_list[i] @ aux)) 
        jac_mi = N.array(pd).reshape((self.dim,))
            
        # compute m-mode Hessian
        hess_mi = N.empty((self.dim, self.dim), dtype='complex128')
        aux = (C_inv_D - 0.5*Identity) @ C_inv
        for i in range(self.dim):
            for j in range(i, self.dim):
                hess_mi[i, j] = hess_mi[j, i] = 2. * N.trace(Q_alpha_list[i] @ C_inv @ Q_alpha_list[j] @ aux)
                
        return fun_mi.real, jac_mi.real, hess_mi.real


        
        
        
 
    
