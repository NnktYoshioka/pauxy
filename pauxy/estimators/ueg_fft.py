# from pauxy.estimators.ueg import local_energy_ueg
try:
    from pauxy.estimators.ueg_kernels  import  exchange_greens_function_per_qvec
except ImportError:
    print("exchange_greens_function_per_qvec doesn't exist")
    exit()

try:
    from pauxy.estimators.ueg_kernels  import  exchange_greens_function_fft
except ImportError:
    print("exchange_greens_function_fft doesn't exist")
    exit()

import time
from pauxy.estimators.ueg import coulomb_greens_function
from pauxy.estimators.utils import convolve
import numpy
import itertools
import scipy.signal

def local_energy_ueg_fft(system, G, Ghalf, two_rdm=None):
    """Local energy computation for uniform electron gas
    Parameters
    ----------
    system :
        system class
    G :
        Green's function
    Returns
    -------
    etot : float
        total energy
    ke : float
        kinetic energy
    pe : float
        potential energy
    """

    CTdagger = numpy.array([numpy.array(system.trial.psi[:,0:system.nup],dtype=numpy.complex128).T.conj(),
    numpy.array(system.trial.psi[:,system.nup:],dtype=numpy.complex128).T.conj()])

    # ke = numpy.einsum('sij,sji->', system.H1, G) # Wrong convention (correct Joonho convention)
    ke = numpy.einsum('sij,sij->', system.H1, G) # Correct pauxy convention

    ne = [system.nup, system.ndown]
    nq = numpy.shape(system.qvecs)[0]

    nocc = [system.nup, system.ndown]
    nqgrid = numpy.prod(system.qmesh)
    ngrid = numpy.prod(system.mesh)

    Gkpq =  numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)
    Gpmq =  numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)

    for s in [0,1]:
        for i in range(nocc[s]):
            ###################################
            Gh_i = numpy.flip(Ghalf[s][i,:])
            CTdagger_i = CTdagger[s][i,:]

            Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_i_cube[system.gmap] = Gh_i
            CTdagger_i_cube[system.gmap] = CTdagger_i

            # \sum_G CT(G-Q) theta(G)
            lQ_i_cube = numpy.flip(convolve(CTdagger_i_cube, Gh_i_cube, system.mesh))
            Gpmq[s] += lQ_i_cube[system.qmap]

            # ################################################################

            Gh_i = Ghalf[s][i,:]
            CTdagger_i = numpy.flip(CTdagger[s][i,:])

            Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_i_cube[system.gmap] = Gh_i
            CTdagger_i_cube[system.gmap] = CTdagger_i

            # \sum_G CT(G+Q) theta(G)
            lQ_i_cube =  numpy.flip(convolve(Gh_i_cube, CTdagger_i_cube, system.mesh))
            Gkpq[s] += lQ_i_cube[system.qmap]


            
    Gprod = numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)
    for s in [0,1]:
        Gprod[s] = exchange_greens_function_fft(nocc[s], system.nbasis, numpy.array(system.mesh), numpy.array(system.qmesh), 
            numpy.array(system.gmap), numpy.array(system.qmap),
            CTdagger[s], Ghalf[s])
        # for i,j in itertools.product(range(nocc[s]), range(nocc[s])):
# def exchange_greens_function_fft (long nocc, long nbsf,  
#     long[:] mesh, long[:] qmesh, long[:] gmap, long[:] qmap,
#     double complex[:,:] CTdagger, double complex[:,:] Ghalf, double complex[:] Gprod):

            # ###################################
            # Gh_i = numpy.flip(Ghalf[s][i,:])
            # CTdagger_j = CTdagger[s][j,:]

            # Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            # CTdagger_j_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            # Gh_i_cube[system.gmap] = Gh_i
            # CTdagger_j_cube[system.gmap] = CTdagger_j

            # # \sum_G CT(G-Q) theta(G)
            # lQ_ji_cube = numpy.flip(convolve(CTdagger_j_cube, Gh_i_cube, system.mesh))
            # lQ_ji_fft = lQ_ji_cube[system.qmap]

            # # ################################################################

            # Gh_j = Ghalf[s][j,:]
            # CTdagger_i = numpy.flip(CTdagger[s][i,:])

            # Gh_j_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            # CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            # Gh_j_cube[system.gmap] = Gh_j
            # CTdagger_i_cube[system.gmap] = CTdagger_i

            # # \sum_G CT(G+Q) theta(G)
            # lQ_ij_cube =  numpy.flip(convolve(Gh_j_cube, CTdagger_i_cube, system.mesh))
            # lQ_ij_fft = lQ_ij_cube[system.qmap]
            
            # Gprod[s] += lQ_ji_fft*lQ_ij_fft

    # print("ek = {}".format(numpy.sum(ek)))

    if two_rdm is None:
        two_rdm = numpy.zeros((2,2,len(system.qvecs)), dtype=numpy.complex128)
    two_rdm[0,0] = numpy.multiply(Gkpq[0],Gpmq[0]) - Gprod[0]
    essa = (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[0,0])

    two_rdm[1,1] = numpy.multiply(Gkpq[1],Gpmq[1]) - Gprod[1]
    essb = (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[1,1])

    two_rdm[0,1] = numpy.multiply(Gkpq[0],Gpmq[1])
    two_rdm[1,0] = numpy.multiply(Gkpq[1],Gpmq[0])
    eos = (
        (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[0,1])
        + (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[1,0])
    )
    pe = essa + essb + eos

    return (ke+pe, ke, pe)

def local_energy_ueg_fft_no_cython(system, G, Ghalf, two_rdm=None):
    """Local energy computation for uniform electron gas
    Parameters
    ----------
    system :
        system class
    G :
        Green's function
    Returns
    -------
    etot : float
        total energy
    ke : float
        kinetic energy
    pe : float
        potential energy
    """

    CTdagger = numpy.array([numpy.array(system.trial.psi[:,0:system.nup],dtype=numpy.complex128).T.conj(),
    numpy.array(system.trial.psi[:,system.nup:],dtype=numpy.complex128).T.conj()])

    # ke = numpy.einsum('sij,sji->', system.H1, G) # Wrong convention (correct Joonho convention)
    ke = numpy.einsum('sij,sij->', system.H1, G) # Correct pauxy convention

    ne = [system.nup, system.ndown]
    nq = numpy.shape(system.qvecs)[0]

    nocc = [system.nup, system.ndown]
    nqgrid = numpy.prod(system.qmesh)
    ngrid = numpy.prod(system.mesh)

    Gkpq =  numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)
    Gpmq =  numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)

    for s in [0,1]:
        for i in range(nocc[s]):
            ###################################
            Gh_i = numpy.flip(Ghalf[s][i,:])
            CTdagger_i = CTdagger[s][i,:]

            Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_i_cube[system.gmap] = Gh_i
            CTdagger_i_cube[system.gmap] = CTdagger_i

            # \sum_G CT(G-Q) theta(G)
            lQ_i_cube = numpy.flip(convolve(CTdagger_i_cube, Gh_i_cube, system.mesh))
            Gpmq[s] += lQ_i_cube[system.qmap]

            # ################################################################

            Gh_i = Ghalf[s][i,:]
            CTdagger_i = numpy.flip(CTdagger[s][i,:])

            Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_i_cube[system.gmap] = Gh_i
            CTdagger_i_cube[system.gmap] = CTdagger_i

            # \sum_G CT(G+Q) theta(G)
            lQ_i_cube =  numpy.flip(convolve(Gh_i_cube, CTdagger_i_cube, system.mesh))
            Gkpq[s] += lQ_i_cube[system.qmap]

    Gprod = numpy.zeros((2,len(system.qvecs)), dtype=numpy.complex128)

    for s in [0,1]:
        for i,j in itertools.product(range(nocc[s]), range(nocc[s])):

            ###################################
            Gh_i = numpy.flip(Ghalf[s][i,:])
            CTdagger_j = CTdagger[s][j,:]

            Gh_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_j_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_i_cube[system.gmap] = Gh_i
            CTdagger_j_cube[system.gmap] = CTdagger_j

            # \sum_G CT(G-Q) theta(G)
            lQ_ji_cube = numpy.flip(convolve(CTdagger_j_cube, Gh_i_cube, system.mesh))
            lQ_ji_fft = lQ_ji_cube[system.qmap]

            # ################################################################

            Gh_j = Ghalf[s][j,:]
            CTdagger_i = numpy.flip(CTdagger[s][i,:])

            Gh_j_cube = numpy.zeros(ngrid, dtype=numpy.complex128)
            CTdagger_i_cube = numpy.zeros(ngrid, dtype=numpy.complex128)

            Gh_j_cube[system.gmap] = Gh_j
            CTdagger_i_cube[system.gmap] = CTdagger_i

            # \sum_G CT(G+Q) theta(G)
            lQ_ij_cube =  numpy.flip(convolve(Gh_j_cube, CTdagger_i_cube, system.mesh))
            lQ_ij_fft = lQ_ij_cube[system.qmap]
            
            Gprod[s] += lQ_ji_fft*lQ_ij_fft

    if two_rdm is None:
        two_rdm = numpy.zeros((2,2,len(system.qvecs)), dtype=numpy.complex128)
    two_rdm[0,0] = numpy.multiply(Gkpq[0],Gpmq[0]) - Gprod[0]
    essa = (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[0,0])

    two_rdm[1,1] = numpy.multiply(Gkpq[1],Gpmq[1]) - Gprod[1]
    essb = (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[1,1])

    two_rdm[0,1] = numpy.multiply(Gkpq[0],Gpmq[1])
    two_rdm[1,0] = numpy.multiply(Gkpq[1],Gpmq[0])
    eos = (
        (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[0,1])
        + (1.0/(2.0*system.vol))*system.vqvec.dot(two_rdm[1,0])
    )
    pe = essa + essb + eos

    return (ke+pe, ke, pe)



def unit_test():
    from pauxy.systems.ueg_fft import UEG_FFT
    import numpy as np
    from pauxy.estimators.greens_function import gab_mod

    from pauxy.systems.ueg import UEG
    from pauxy.estimators.ueg import local_energy_ueg

    from pauxy.utils.testing import get_random_wavefunction

    ecuts = [100.0]
    # ecuts = [2.0]
    # ecuts = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0]

    for ecut in ecuts:
        inputs = {'nup':7,
        'ndown':7,
        'rs':1.0,
        'ecut':ecut, 'skip_cholesky':True}
        system = UEG_FFT(inputs, False)
        print ("ecut = {}, nbsf = {}".format(ecut, system.nbasis))
    
        np.random.seed(7)
    
        # sort_basis = numpy.argsort(numpy.diag(system.H1[0]), kind='mergesort')
        # psi = get_random_wavefunction((system.nbasis,system.nbasis), system.nbasis)
    
        # psi_a = psi[:,:system.nbasis].copy()
        # psi_b = psi[:,system.nbasis:].copy()
    
        # cocca = psi_a[:,sort_basis]
        # coccb = psi_b[:,sort_basis]
    
        # system.trial.psi[:,:system.nup] = cocca[:, :system.nup]
        # system.trial.psi[:,system.nup:] = coccb[:, :system.ndown]
        
        Ca = np.array(system.trial.psi[:,0:system.nup],dtype=np.complex128)
        Cb = np.array(system.trial.psi[:,system.nup:],dtype=np.complex128)
    
        (G_a, Ghalf_a) = gab_mod(Ca, Ca)
        (G_b, Ghalf_b) = gab_mod(Cb, Cb)
    
        G = np.array([G_a, G_b])
        Ghalf = np.array([Ghalf_a, Ghalf_b])
    
        start = time.time()
        etot, ekin, epot = local_energy_ueg_fft(system, G=G, Ghalf=Ghalf)
        print("ERHF = {}, {}, {}".format(etot, ekin, epot))
        end = time.time()
        print("FFT local energy (s): {}".format(end - start))
    
        start = time.time()
        etot, ekin, epot = local_energy_ueg_fft_no_cython(system, G=G, Ghalf=Ghalf)
        print("ERHF = {}, {}, {}".format(etot, ekin, epot))
        end = time.time()
        print("FFT w/o Cython local energy (s): {}".format(end - start))
    
        # start = time.time()
        # etot, ekin, epot = local_energy_ueg_scipy(system, G=G, Ghalf=Ghalf)
        # print("ERHF = {}, {}, {}".format(etot, ekin, epot))
        # end = time.time()
        # print("SciPY local energy (s): {}".format(end - start))
    
    
        # Greorder = G.copy()
        # for s in [0,1]:
        #     for i in range(system.nbasis):
        #         for j in range(system.nbasis):
        #             Greorder[s][i,j] = G[s][sort_basis[i],sort_basis[j]]
        system2 = UEG(inputs, False)
        nbsf = system2.nbasis
        Pa = np.zeros([nbsf,nbsf],dtype = np.complex128)
        Pb = np.zeros([nbsf,nbsf],dtype = np.complex128)
        na = system.nup
        nb = system.ndown
        for i in range(na):
            Pa[i,i] = 1.0
        for i in range(nb):
            Pb[i,i] = 1.0
        P = np.array([Pa, Pb])
    
        start = time.time()
        etot, ekin, epot = local_energy_ueg(system2, G=P)
        print("ERHF = {}, {}, {}".format(etot, ekin, epot))
        end = time.time()
        print("Usual local energy (s): {}".format(end - start))

    # print(Greorder[0])
    # print(G[0])

    # print(numpy.diag(system.H1[0])[sort_basis])
    # print(system2.H1)
# ERHF = (13.603557335564197+0j), (15.692780148560848+0j), (-2.0892228129966512+0j) #(7e,7e)


if __name__=="__main__":
    unit_test()
