

"""
functions to calculate two point correlation functions
"""

from __future__ import division, print_function

__all__=['tpcf','tpcf_jackknife','redshift_space_tpcf','wp']

####import modules########################################################################
import sys
import numpy as np
from math import pi, gamma
from .pair_counters.grid_pairs import npairs, xy_z_npairs, jnpairs
##########################################################################################

def tpcf(sample1, rbins,
         sample2 = None, randoms=None, period = None,
         max_sample_size=int(1e6), do_auto=True, do_cross=True, estimator='Natural',
         N_threads=1, comm=None):
    """ 
    Calculate the two-point correlation function. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts. 
    
    rbins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrbins + 1.
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like, optional
        Nran x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.
    
    comm: mpi Intracommunicator object, optional
    
    do_auto: boolean, optional
        do auto-correlation?
    
    do_cross: boolean, optional
        do cross-correlation?

    Returns 
    -------
    correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the Nrbins 
        defined by input `rbins`.

        :math:`1 + \\xi(r) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if sample2 is not None: sample2 = np.asarray(sample2)
    else: sample2 = sample1
    if randoms is not None: randoms = np.asarray(randoms)
    rbins = np.asarray(rbins)
    #Process period entry and check for consistency.
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(sample1)[-1])
        elif np.shape(period)[0] != np.shape(sample1)[-1]:
            raise ValueError("period should have shape (k,)")
            return None
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    
    if np.shape(rbins) == ():
        rbins = np.array([rbins])
    
    k = np.shape(sample1)[-1] #dimensionality of data
    
    #check for input parameter consistency
    if (period is not None) & (np.max(rbins)>np.min(period)/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (sample2 is not None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if (randoms is None) & (min(period)==np.inf):
        raise ValueError('If no PBCs are specified, randoms must be provided.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))
    if (PBCs==True) & (max(period)==np.inf):
        raise ValueError('If a non-infinte PBC specified, all PBCs must be non-infinte.')

    #If PBCs are defined, calculate the randoms analytically. Else, the user must specify 
    #randoms and the pair counts are calculated the old fashion way.
    def random_counts(sample1, sample2, randoms, rbins, period, PBCs, k, N_threads, do_RR, do_DR, comm):
        """
        Count random pairs.  There are three high level branches: 
            1. no PBCs w/ randoms.
            2. PBCs w/ randoms
            3. PBCs and analytical randoms
        There are also logical bits to do RR and DR pair counts, as not all estimators 
        need one or the other, and not doing these can save a lot of calculation.
        """
        def nball_volume(R,k):
            """
            Calculate the volume of a n-shpere.  This is used for the analytical randoms.
            """
            return (pi**(k/2.0)/gamma(k/2.0+1.0))*R**k
        
        #No PBCs, randoms must have been provided.
        if PBCs==False:
            RR = npairs(randoms, randoms, rbins, period=period)
            RR = np.diff(RR)
            D1R = npairs(sample1, randoms, rbins, period=period)
            D1R = np.diff(D1R)
            if np.all(sample1 == sample2): #calculating the cross-correlation
                D2R = None
            else:
                D2R = npairs(sample2, randoms, rbins, period=period)
                D2R = np.diff(D2R)
            
            return D1R, D2R, RR
        #PBCs and randoms.
        elif randoms is not None:
            if do_RR==True:
                RR = npairs(randoms, randoms, rbins, period=period)
                RR = np.diff(RR)
            else: RR=None
            if do_DR==True:
                D1R = npairs(sample1, randoms, rbins, period=period)
                D1R = np.diff(D1R)
            else: D1R=None
            if np.all(sample1 == sample2): #calculating the cross-correlation
                D2R = None
            else:
                if do_DR==True:
                    D2R = npairs(sample2, randoms, rbins, period=period)
                    D2R = np.diff(D2R)
                else: D2R=None
            
            return D1R, D2R, RR
        #PBCs and no randoms--calculate randoms analytically.
        elif randoms is None:
            #do volume calculations
            dv = nball_volume(rbins,k) #volume of spheres
            dv = np.diff(dv) #volume of shells
            global_volume = period.prod() #sexy
            
            #calculate randoms for sample1
            N1 = np.shape(sample1)[0]
            rho1 = N1/global_volume
            D1R = (N1)*(dv*rho1) #read note about pair counter
            
            #if not calculating cross-correlation, set RR exactly equal to D1R.
            if np.all(sample1 == sample2):
                D2R = None
                RR = D1R #in the analytic case, for the auto-correlation, DR==RR.
            else: #if there is a sample2, calculate randoms for it.
                N2 = np.shape(sample2)[0]
                rho2 = N2/global_volume
                D2R = N2*(dv*rho2) #read note about pair counter
                #calculate the random-random pairs.
                NR = N1*N2
                rhor = NR/global_volume
                RR = (dv*rhor) #RR is only the RR for the cross-correlation.

            return D1R, D2R, RR
        else:
            raise ValueError('Un-supported combination of PBCs and randoms provided.')
    
    def pair_counts(sample1, sample2, rbins, period, N_thread, do_auto, do_cross, do_DD, comm):
        """
        Count data pairs.
        """
        D1D1 = npairs(sample1, sample1, rbins, period=period)
        D1D1 = np.diff(D1D1)
        if np.all(sample1 == sample2):
            D1D2 = D1D1
            D2D2 = D1D1
        else:
            D1D2 = npairs(sample1, sample2, rbins, period=period)
            D1D2 = np.diff(D1D2)
            D2D2 = npairs(sample2, sample2, rbins, period=period)
            D2D2 = np.diff(D2D2)

        return D1D1, D1D2, D2D2
        
    def TP_estimator(DD,DR,RR,ND1,ND2,NR1,NR2,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            factor = ND1*ND2/(NR1*NR2)
            #DD/RR-1
            xi = (1.0/factor)*DD/RR - 1.0
        elif estimator == 'Davis-Peebles':
            factor = ND1*ND2/(ND1*NR2)
            #DD/DR-1
            xi = (1.0/factor)*DD/DR - 1.0
        elif estimator == 'Hewett':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            #(DD-DR)/RR
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*DR/RR
        elif estimator == 'Hamilton':
            #DDRR/DRDR-1
            xi = (DD*RR)/(DR*DR) - 1.0
        elif estimator == 'Landy-Szalay':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            #(DD - 2.0*DR + RR)/RR
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*2.0*DR/RR + 1.0
        else: 
            raise ValueError("unsupported estimator!")
        return xi
    
    def TP_estimator_requirements(estimator):
        """
        return booleans indicating which pairs need to be counted for the chosen estimator
        """
        if estimator == 'Natural':
            do_DD = True
            do_DR = False
            do_RR = True
        elif estimator == 'Davis-Peebles':
            do_DD = True
            do_DR = True
            do_RR = False
        elif estimator == 'Hewett':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Hamilton':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Landy-Szalay':
            do_DD = True
            do_DR = True
            do_RR = True
        else: 
            raise ValueError("unsupported estimator!")
        return do_DD, do_DR, do_RR
    
    do_DD, do_DR, do_RR = TP_estimator_requirements(estimator)
              
    if randoms is not None:
        N1 = len(sample1)
        N2 = len(sample2)
        NR = len(randoms)
    else: 
        N1 = 1.0
        N2 = 1.0
        NR = 1.0
    
    #count pairs
    D1D1,D1D2,D2D2 = pair_counts(sample1, sample2, rbins, period,\
                                 N_threads, do_auto, do_cross, do_DD, comm)
    D1R, D2R, RR = random_counts(sample1, sample2, randoms, rbins, period,\
                                 PBCs, k, N_threads, do_RR, do_DR, comm)
    
    if np.all(sample2==sample1):
        xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
        return xi_11
    else:
        if (do_auto==True) & (do_cross==True): 
            xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,RR,N2,N2,NR,NR,estimator)
            return xi_11, xi_12, xi_22
        elif (do_cross==True):
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            return xi_12
        elif (do_auto==True):
            xi_11 = TP_estimator(D1D1,D1R,D1R,N1,N1,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,D2R,N2,N2,NR,NR,estimator)
            return xi_11


def tpcf_jackknife(sample1, randoms, rbins, Nsub=5, Lbox=[250.0,250.0,250.0], sample2 = None,
                   period = None, max_sample_size=int(1e6),
                   do_auto=True, do_cross=True,estimator='Natural',
                   N_threads=1, comm=None):
    """
    Calculate the two-point correlation function with jackknife errors. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like
        Nran x k numpy array containing k-d positions of Npts. 
    
    rbins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrbins + 1.
    
    Nsub : array_like, optional
        numpy array of number of divisions along each dimension defining jackknife subvolumes
        if single integer is given, assumed to be equivalent for each dimension
    
    Lbox : array_like, optional
        length of data volume along each dimension
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.
    
    comm: mpi Intracommunicator object, optional

    Returns 
    -------
    correlation_function(s), cov_matrix : array_like
        array containing correlation function :math:`\\xi(r)` computed in each of the Nrbins 
        defined by input `rbins`.
        Nrbins x Nrbins array containing the covariance matrix of `\\xi(r)`

    """
    
    #parallel processing things
    if comm!=None:
        rank=comm.rank
    else: rank=0
    if N_threads>1:
        pool = Pool(N_threads)
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if sample2 != None: sample2 = np.asarray(sample2)
    else: sample2 = sample1
    randoms = np.asarray(randoms)
    rbins = np.asarray(rbins)
    if type(Nsub) is int: Nsub = np.array([Nsub]*np.shape(sample1)[-1])
    else: Nsub = np.asarray(Nsub)
    if type(Lbox) in (int,float): Lbox = np.array([Lbox]*np.shape(sample1)[-1])
    else: Lbox = np.asarray(Lbox)
    #Process period entry and check for consistency.
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(sample1)[-1])
        elif np.shape(period)[0] != np.shape(sample1)[-1]:
            raise ValueError("period should have shape (k,)")
            return None
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    if len(randoms)>max_sample_size:
        inds = np.arange(0,len(randoms))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = randoms[inds]
        print('down sampling randoms...')
    if np.shape(Nsub)[0]!=np.shape(sample1)[-1]:
        raise ValueError("Nsub should have shape (k,) or be a single integer")
    
    if np.shape(rbins) == ():
        rbins = np.array([rbins])
    
    k = np.shape(sample1)[-1] #dimensionality of data
    N1 = len(sample1)
    N2 = len(sample2)
    Nran = len(randoms)
    
    #check for input parameter consistency
    if (period != None) & (np.max(rbins)>np.min(period)/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (sample2 != None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))
    if (PBCs==True) & (max(period)==np.inf):
        raise ValueError('If a non-infinte PBC specified, all PBCs must be non-infinte.')
    
    def get_subvolume_labels(sample1, sample2, randoms, Nsub, Lbox):
        """
        Split volume into subvolumes, and tag points in subvolumes with integer labels for 
        use in the jackknife calculation.
        
        note: '0' tag should be reserved. It is used in the jackknife calculation to mean
        'full sample'
        """
        
        dL = Lbox/Nsub # length of subvolumes along each dimension
        N_sub_vol = np.prod(Nsub) # total the number of subvolumes
        inds = np.arange(1,N_sub_vol+1).reshape(Nsub[0],Nsub[1],Nsub[2])
    
        #tag each particle with an integer indicating which jackknife subvolume it is in
        #subvolume indices for the sample1 particle's positions
        index_1 = np.floor(sample1/dL).astype(int)
        j_index_1 = inds[index_1[:,0],index_1[:,1],index_1[:,2]].astype(int)
    
        #subvolume indices for the random particle's positions
        index_random = np.floor(randoms/dL).astype(int)
        j_index_random = inds[index_random[:,0],index_random[:,1],index_random[:,2]].astype(int)
        
        #subvolume indices for the sample2 particle's positions
        index_2 = np.floor(sample2/dL).astype(int)
        j_index_2 = inds[index_2[:,0],index_2[:,1],index_2[:,2]].astype(int)
        
        return j_index_1, j_index_2, j_index_random, int(N_sub_vol)
    
    def get_subvolume_numbers(j_index,N_sub_vol):
        temp = np.hstack((j_index,np.arange(1,N_sub_vol+1,1))) #kinda hacky, but need to every label to be in there at least once
        labels, N = np.unique(temp,return_counts=True)
        N = N-1 #remove the place holder I added two lines above.
        return N
    
    def jnpair_counts(sample1, sample2, j_index_1, j_index_2, N_sub_vol, rbins,\
                      period, N_thread, do_auto, do_cross, do_DD, comm):
        """
        Count jackknife data pairs: DD
        """
        D1D1 = jnpairs(sample1, sample1, rbins, period=period,\
                       jtags1=j_index_1, jtags2=j_index_1,  N_samples=N_sub_vol)
        D1D1 = np.diff(D1D1,axis=1)
        if np.all(sample1 == sample2):
            D1D2 = D1D1
            D2D2 = D1D1
        else:
            D1D2 = D1D1
            D2D2 = D1D1
            D1D2 = jnpairs(sample1, sample2, rbins, period=period,\
                           jtags1=j_index_1, jtags2=j_index_2,\
                            N_samples=N_sub_vol)
            D1D2 = np.diff(D1D2,axis=1)
            D2D2 = jnpairs(sample2, sample2, rbins, period=period,\
                           jtags1=j_index_2, jtags2=j_index_2,\
                            N_samples=N_sub_vol)
            D2D2 = np.diff(D2D2,axis=1)

        return D1D1, D1D2, D2D2
    
    def jrandom_counts(sample, randoms, j_index, j_index_randoms, N_sub_vol, rbins,\
                       period, N_thread, do_DR, do_RR, comm):
        """
        Count jackknife random pairs: DR, RR
        """
        
        if do_DR==True:
            DR = jnpairs(sample, randoms, rbins, period=period,\
                         jtags1=j_index, jtags2=j_index_randoms,\
                          N_samples=N_sub_vol)
            DR = np.diff(DR,axis=1)
        else: DR=None
        if do_RR==True:
            RR = jnpairs(randoms, randoms, rbins, period=period,\
                         jtags1=j_index_randoms, jtags2=j_index_randoms,\
                         N_samples=N_sub_vol)
            RR = np.diff(RR,axis=1)
        else: RR=None

        return DR, RR
        
    def TP_estimator(DD,DR,RR,ND1,ND2,NR1,NR2,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            factor = ND1*ND2/(NR1*NR2)
            xi = (1.0/factor)*(DD/RR).T - 1.0 #DD/RR-1
        elif estimator == 'Davis-Peebles':
            factor = ND1*ND2/(ND1*NR2)
            xi = (1.0/factor)*(DD/DR).T - 1.0 #DD/DR-1
        elif estimator == 'Hewett':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*(DD/RR).T - (1.0/factor2)*(DR/RR).T #(DD-DR)/RR
        elif estimator == 'Hamilton':
            xi = (DD*RR)/(DR*DR) - 1.0 #DDRR/DRDR-1
        elif estimator == 'Landy-Szalay':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*(DD/RR).T - (1.0/factor2)*2.0*(DR/RR).T + 1.0 #(DD - 2.0*DR + RR)/RR
        else: 
            raise ValueError("unsupported estimator!")
        return xi.T #had to transpose twice to get the multiplication to work for the jackknife samples
    
    def TP_estimator_requirements(estimator):
        """
        return booleans indicating which pairs need to be counted for the chosen estimator
        """
        if estimator == 'Natural':
            do_DD = True
            do_DR = False
            do_RR = True
        elif estimator == 'Davis-Peebles':
            do_DD = True
            do_DR = True
            do_RR = False
        elif estimator == 'Hewett':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Hamilton':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Landy-Szalay':
            do_DD = True
            do_DR = True
            do_RR = True
        else: 
            raise ValueError("unsupported estimator!")
        return do_DD, do_DR, do_RR
    
    def jackknife_errors(sub,full,N_sub_vol):
        """
        Calculate jackknife errors.
        """
        after_subtraction =  sub - np.mean(sub,axis=0)
        squared = after_subtraction**2.0
        error2 = ((N_sub_vol-1)/N_sub_vol)*squared.sum(axis=0)
        error = error2**0.5
        
        return error
    
    def covariance_matrix(sub,full,N_sub_vol):
        """
        Calculate the full covariance matrix.
        """
        Nr = full.shape[0] # Nr is the number of radial bins
        cov = np.zeros((Nr,Nr)) # 2D array that keeps the covariance matrix 
        after_subtraction = sub - np.mean(sub,axis=0)
        tmp = 0
        for i in range(Nr):
            for j in range(Nr):
                tmp = 0.0
                for k in range(N_sub_vol):
                    tmp = tmp + after_subtraction[k,i]*after_subtraction[k,j]
                cov[i,j] = (((N_sub_vol-1)/N_sub_vol)*tmp)
    
        return cov
    
    do_DD, do_DR, do_RR = TP_estimator_requirements(estimator)
    
    N1 = len(sample1)
    N2 = len(sample2)
    NR = len(randoms)
    
    j_index_1, j_index_2, j_index_random, N_sub_vol = \
                               get_subvolume_labels(sample1, sample2, randoms, Nsub, Lbox)
    
    #number of points in each subvolume
    NR_subs = get_subvolume_numbers(j_index_random,N_sub_vol)
    N1_subs = get_subvolume_numbers(j_index_1,N_sub_vol)
    N2_subs = get_subvolume_numbers(j_index_2,N_sub_vol)
    #number of points in each jackknife sample
    N1_subs = N1 - N1_subs
    N2_subs = N2 - N2_subs
    NR_subs = NR - NR_subs
    
    #calculate all the pair counts
    D1D1, D1D2, D2D2 = jnpair_counts(sample1, sample2, j_index_1, j_index_2, N_sub_vol,\
                                     rbins, period, N_threads, do_auto, do_cross, do_DD, comm)
    D1D1_full = D1D1[0,:]
    D1D1_sub = D1D1[1:,:]
    D1D2_full = D1D2[0,:]
    D1D2_sub = D1D2[1:,:]
    D2D2_full = D2D2[0,:]
    D2D2_sub = D2D2[1:,:]
    D1R, RR = jrandom_counts(sample1, randoms, j_index_1, j_index_random, N_sub_vol,\
                             rbins, period, N_threads, do_DR, do_RR, comm)
    if np.all(sample1==sample2):
        D2R=D1R
    else:
        if do_DR==True:
            D2R, RR_dummy= jrandom_counts(sample2, randoms, j_index_2, j_index_random,\
                                      N_sub_vol, rbins, period, N_threads, do_DR, False, comm)
        else: D2R = None
    
    if do_DR==True:    
        D1R_full = D1R[0,:]
        D1R_sub = D1R[1:,:]
        D2R_full = D2R[0,:]
        D2R_sub = D2R[1:,:]
    else:
        D1R_full = None
        D1R_sub = None
        D2R_full = None
        D2R_sub = None
    if do_RR==True:
        RR_full = RR[0,:]
        RR_sub = RR[1:,:]
    else:
        RR_full = None
        RR_sub = None
    
    
    #calculate the correlation function for the full sample
    xi_11_full = TP_estimator(D1D1_full,D1R_full,RR_full,N1,N1,NR,NR,estimator)
    xi_12_full = TP_estimator(D1D2_full,D1R_full,RR_full,N1,N2,NR,NR,estimator)
    xi_22_full = TP_estimator(D2D2_full,D2R_full,RR_full,N2,N2,NR,NR,estimator)
    #calculate the correlation function for the subsamples
    xi_11_sub = TP_estimator(D1D1_sub,D1R_sub,RR_sub,N1_subs,N1_subs,NR_subs,NR_subs,estimator)
    xi_12_sub = TP_estimator(D1D2_sub,D1R_sub,RR_sub,N1_subs,N2_subs,NR_subs,NR_subs,estimator)
    xi_22_sub = TP_estimator(D2D2_sub,D2R_sub,RR_sub,N2_subs,N2_subs,NR_subs,NR_subs,estimator)
    
    #calculate the errors
    xi_11_err = jackknife_errors(xi_11_sub,xi_11_full,N_sub_vol)
    xi_12_err = jackknife_errors(xi_12_sub,xi_12_full,N_sub_vol)
    xi_22_err = jackknife_errors(xi_22_sub,xi_22_full,N_sub_vol)
    
    #calculate the covariance matrix
    xi_11_cov = covariance_matrix(xi_11_sub,xi_11_full,N_sub_vol)
    xi_12_cov = covariance_matrix(xi_12_sub,xi_12_full,N_sub_vol)
    xi_22_cov = covariance_matrix(xi_22_sub,xi_22_full,N_sub_vol)
    
    if np.all(sample1==sample2):
        return xi_11_full,xi_11_cov
    else:
        if (do_auto==True) & (do_cross==True):
            return xi_11_full,xi_12_full,xi_22_full,xi_11_cov,xi_12_cov,xi_22_cov
        elif do_auto==True:
            return xi_11_full,xi_22_full,xi_11_cov,xi_22_cov
        elif do_cross==True:
            return xi_12_full,xi_12_cov


def redshift_space_tpcf(sample1, rp_bins, pi_bins, sample2 = None, randoms=None, 
                        period = None, max_sample_size=int(1e6),
                        do_auto=True, do_cross=True, estimator='Natural', 
                        N_threads=1, comm=None):
    """ 
    Calculate the redshift space correlation function.  The first two dimensions define
    the plane for perpendicular distances.  The third dimension is used for parallel 
    distances.  i.e. x,y positions are on the plane of the sky, and z is the redshift 
    coordinate.
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts. 
    
    rp_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrp_bins + 1.
    
    pi_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(pi_bins) = Npi_bins + 1.
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like, optional
        Nran x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.
    
    comm: mpi Intracommunicator object, optional
    
    do_auto: boolean, optional
        do auto-correlation?
    
    do_cross: boolean, optional
        do cross-correlation?

    Returns 
    -------
    correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the 
        Nrp_bins X Npi_bins defined by input `rp_bins` and `pi_bins`.

        :math:`1 + \\xi(rp,pi) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if sample2 is not None: sample2 = np.asarray(sample2)
    else: sample2 = sample1
    if randoms is not None: randoms = np.asarray(randoms)
    rp_bins = np.asarray(rp_bins)
    pi_bins = np.asarray(pi_bins)
    #Process period entry and check for consistency.
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(sample1)[-1])
        elif np.shape(period)[0] != np.shape(sample1)[-1]:
            raise ValueError("period should have shape (k,)")
            return None
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    
    if np.shape(rp_bins) == ():
        rbins = np.array([rp_bins])
    if np.shape(pi_bins) == ():
        rbins = np.array([pi_bins])
    
    k = np.shape(sample1)[-1] #dimensionality of data
    
    #check for input parameter consistency
    if (period is not None) & (np.max(rp_bins)>np.min(period[0:2])/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (period is not None) & (np.max(pi_bins)>np.min(period[2])/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (sample2 is not None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if (randoms is None) & (min(period)==np.inf):
        raise ValueError('If no PBCs are specified, randoms must be provided.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))
    if (PBCs==True) & (max(period)==np.inf):
        raise ValueError('If a non-infinte PBC specified, all PBCs must be non-infinte.')

    #If PBCs are defined, calculate the randoms analytically. Else, the user must specify 
    #randoms and the pair counts are calculated the old fashion way.
    def random_counts(sample1, sample2, randoms, rp_bins, pi_bins, period,\
                      PBCs, k, N_threads, do_RR, do_DR, comm):
        """
        Count random pairs.  There are three high level branches: 
            1. no PBCs w/ randoms.
            2. PBCs w/ randoms
            3. PBCs and analytical randoms
        Within each of those branches there are 3 branches to use:
            1. MPI
            2. no threads
            3. threads
        There are also logical bits to do RR and DR pair counts, as not all estimators 
        need one or the other, and not doing these can save a lot of calculation.
        """
        def cylinder_volume(R,h):
            """
            Calculate the volume of a cylinder(s), used for the analytical randoms.
            """
            return pi*np.outer(R**2.0,h)
        
        #No PBCs, randoms must have been provided.
        if PBCs==False:
            RR = xy_z_npairs(randoms, randoms, rp_bins, pi_bins, period=period)
            RR = np.diff(np.diff(RR,axis=0),axis=1)
            D1R = xy_z_npairs(sample1, randoms, rp_bins, pi_bins, period=period)
            D1R = np.diff(np.diff(D1R,axis=0),axis=1)
            if np.all(sample1 == sample2): #calculating the cross-correlation
                D2R = None
            else:
                D2R = xy_z_npairs(sample2, randoms, rp_bins, pi_bins, period=period)
                D2R = np.diff(np.diff(D2R,axis=0),axis=1)
            
            return D1R, D2R, RR
        #PBCs and randoms.
        elif randoms is not None:
            if do_RR==True:
                RR = xy_z_npairs(randoms, randoms, rp_bins, pi_bins, period=period)
                RR = np.diff(np.diff(RR,axis=0),axis=1)
            else: RR=None
            if do_DR==True:
                D1R = xy_z_npairs(sample1, randoms, rp_bins, pi_bins, period=period)
                D1R = np.diff(np.diff(D1R,axis=0),axis=1)
            else: D1R=None
            if np.all(sample1 == sample2): #calculating the cross-correlation
                D2R = None
            else:
                if do_DR==True:
                    D2R = xy_z_npairs(sample2, randoms, rp_bins, pi_bins, period=period)
                    D2R = np.diff(np.diff(D2R,axis=0),axis=1)
                else: D2R=None
            
            return D1R, D2R, RR
        #PBCs and no randoms--calculate randoms analytically.
        elif randoms is None:
            #do volume calculations
            dv = cylinder_volume(rp_bins,pi_bins) #volume of spheres
            dv = np.diff(np.diff(dv, axis=0),axis=1) #volume of annuli
            global_volume = period.prod() #sexy
            
            #calculate randoms for sample1
            N1 = np.shape(sample1)[0]
            rho1 = N1/global_volume
            D1R = (N1)*(dv*rho1) #read note about pair counter
            
            #if not calculating cross-correlation, set RR exactly equal to D1R.
            if np.all(sample1 == sample2):
                D2R = None
                RR = D1R #in the analytic case, for the auto-correlation, DR==RR.
            else: #if there is a sample2, calculate randoms for it.
                N2 = np.shape(sample2)[0]
                rho2 = N2/global_volume
                D2R = N2*(dv*rho2) #read note about pair counter
                #calculate the random-random pairs.
                NR = N1*N2
                rhor = NR/global_volume
                RR = (dv*rhor) #RR is only the RR for the cross-correlation.

            return D1R, D2R, RR
        else:
            raise ValueError('Un-supported combination of PBCs and randoms provided.')
    
    def pair_counts(sample1, sample2, rp_bins, pi_bins, period,\
                    N_thread, do_auto, do_cross, do_DD, comm):
        """
        Count data pairs.
        """
        D1D1 = xy_z_npairs(sample1, sample1, rp_bins, pi_bins, period=period)
        D1D1 = np.diff(np.diff(D1D1,axis=0),axis=1)
        if np.all(sample1 == sample2):
            D1D2 = D1D1
            D2D2 = D1D1
        else:
            D1D2 = xy_z_npairs(sample1, sample2, rp_bins, pi_bins, period=period)
            D1D2 = np.diff(np.diff(D1D2,axis=0),axis=1)
            D2D2 = xy_z_npairs(sample2, sample2, rp_bins, pi_bins, period=period)
            D2D2 = np.diff(np.diff(D2D2,axis=0),axis=1)

        return D1D1, D1D2, D2D2
        
    def TP_estimator(DD,DR,RR,ND1,ND2,NR1,NR2,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            factor = ND1*ND2/(NR1*NR2)
            #DD/RR-1
            xi = (1.0/factor)*DD/RR - 1.0
        elif estimator == 'Davis-Peebles':
            factor = ND1*ND2/(ND1*NR2)
            #DD/DR-1
            xi = (1.0/factor)*DD/DR - 1.0
        elif estimator == 'Hewett':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            #(DD-DR)/RR
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*DR/RR
        elif estimator == 'Hamilton':
            #DDRR/DRDR-1
            xi = (DD*RR)/(DR*DR) - 1.0
        elif estimator == 'Landy-Szalay':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            #(DD - 2.0*DR + RR)/RR
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*2.0*DR/RR + 1.0
        else: 
            raise ValueError("unsupported estimator!")
        return xi
    
    def TP_estimator_requirements(estimator):
        """
        return booleans indicating which pairs need to be counted for the chosen estimator
        """
        if estimator == 'Natural':
            do_DD = True
            do_DR = False
            do_RR = True
        elif estimator == 'Davis-Peebles':
            do_DD = True
            do_DR = True
            do_RR = False
        elif estimator == 'Hewett':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Hamilton':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Landy-Szalay':
            do_DD = True
            do_DR = True
            do_RR = True
        else: 
            raise ValueError("unsupported estimator!")
        return do_DD, do_DR, do_RR
    
    do_DD, do_DR, do_RR = TP_estimator_requirements(estimator)
              
    if randoms is not None:
        N1 = len(sample1)
        N2 = len(sample2)
        NR = len(randoms)
    else: 
        N1 = 1.0
        N2 = 1.0
        NR = 1.0
    
    #count pairs
    D1D1,D1D2,D2D2 = pair_counts(sample1, sample2, rp_bins, pi_bins, period,\
                                 N_threads, do_auto, do_cross, do_DD, comm)
    D1R, D2R, RR = random_counts(sample1, sample2, randoms, rp_bins, pi_bins, period,\
                                 PBCs, k, N_threads, do_RR, do_DR, comm)
    
    if np.all(sample2==sample1):
        xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
        return xi_11
    else:
        if (do_auto==True) & (do_cross==True): 
            xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,RR,N2,N2,NR,NR,estimator)
            return xi_11, xi_12, xi_22
        elif (do_cross==True):
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            return xi_12
        elif (do_auto==True):
            xi_11 = TP_estimator(D1D1,D1R,D1R,N1,N1,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,D2R,N2,N2,NR,NR,estimator)
            return xi_11


def wp(sample1, rp_bins, pi_bins, sample2 = None, randoms=None, 
                        period = None, max_sample_size=int(1e6),
                        do_auto=True, do_cross=True, estimator='Natural', 
                        N_threads=1, comm=None):
    """ 
    Calculate the projected correlation function.  The first two dimensions define
    the plane for perpendicular distances.  The third dimension is used for parallel 
    distances.  i.e. x,y positions are on the plane of the sky, and z is the redshift 
    coordinate. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts. 
    
    rp_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrp_bins + 1.
    
    pi_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(pi_bins) = Npi_bins + 1.
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like, optional
        Nran x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.
    
    comm: mpi Intracommunicator object, optional
    
    do_auto: boolean, optional
        do auto-correlation?
    
    do_cross: boolean, optional
        do cross-correlation?

    Returns 
    -------
    correlation_function : array_like
        array containing correlation function :math:`\\w_p` computed in each of the Nrbins 
        defined by input `rp_bins`.

        :math:`1 + \\w_p(r) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """

    result = redshift_space_tpcf(sample1, rp_bins, pi_bins,\
                                 sample2 = sample2, randoms=randoms,\
                                 period = period, max_sample_size=max_sample_size,\
                                 do_auto=do_auto, do_cross=do_cross, estimator=estimator,\
                                 N_threads=1, comm=comm)

    if np.all(sample2==sample1): do_cross=False
    if sample2 is None: do_cross=False

    def integrate_2D_xi(x,pi_bins):
        return np.sum(x*np.diff(pi_bins),axis=1)

    #integrate Xi to get wp
    if (do_auto==True) & (do_cross==True):
        wp_D1D1 = integrate_2D_xi(result[0],pi_bins)
        wp_D1D2 = integrate_2D_xi(result[1],pi_bins)
        wp_D2D2 = integrate_2D_xi(result[2],pi_bins)
        return wp_D1D1, wp_D1D2, wp_D2D2
    elif (do_auto==False) & (do_cross==True):
        wp_D1D2 = integrate_2D_xi(result,pi_bins)
        return wp_D1D2
    else:
        wp_D1D1 = integrate_2D_xi(result,pi_bins)
        return wp_D1D1
    
    
