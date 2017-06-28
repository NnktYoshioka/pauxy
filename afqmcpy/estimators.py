"""Routines and classes for estimation of observables."""
import numpy
import time
from enum import Enum
from mpi4py import MPI
import scipy.linalg
import afqmcpy.utils


class Estimators():
    """Container for qmc estimates of observables.

    Attributes
    ----------
    header : list of strings
        Default estimates and simulation information.
    funit : file unit
        File to write back-propagated estimates to.
    back_propagated_header : list of strings
        Back-propagated estimates.
    nestimators : int
        Number of estimators.
    names : :class:`afqmcpy.estimators.EstimatorEnum`
        Enum type object to allow for clearer (maybe) indexing.
    estimates : :class:`numpy.ndarray`
        Array containing accumulated estimates.
        See afqmcpy.estimators.Estimates.print_key for description.
    """

    def __init__(self, state):
        self.header = ['iteration', 'Weight', 'E_num', 'E_denom', 'E', 'time']
        if state.root:
            self.print_key()
        if state.back_propagation:
            if state.root:
                self.funit = open('back_propagated_estimates_%s.out'%state.uuid[:8], 'a')
                state.write_json(print_function=self.funit.write, eol='\n',
                                 verbose=True)
                self.print_key(state.back_propagation, self.funit.write,
                               eol='\n')
            self.back_propagated_header = ['iteration', 'E', 'T', 'V']
            if state.itcf:
                if state.root:
                    self.itcf_unit = open('spgf_%s.out'%state.uuid[:8], 'ab')
                    state.write_json(print_function=self.itcf_unit.write, eol='\n',
                                     verbose=True, encode=True)
                    self.print_key(state.back_propagation, self.funit.write,
                                   eol='\n')
                self.ifcf_header = ['tau', 'g00']
            # don't communicate the estimators header
            self.nestimators = len(self.header+self.back_propagated_header) - 2
            self.names = EstimatorEnum(self.nestimators)
        else:
            self.nestimators = len(self.header)
            self.names = EstimatorEnum(self.nestimators+3)
        # only store up component for the moment.
        self.spgf = numpy.zeros(shape=(state.itcf_nmax+1, state.system.nbasis,
                                       state.system.nbasis))
        self.estimates = numpy.zeros(self.nestimators+len(self.spgf.flatten()))
        self.zero(state)


    def zero(self, state):
        """Zero estimates.

        On return self.estimates is zerod and the timers are reset.

        """
        self.estimates[:] = 0
        self.estimates[self.names.time] = time.time()
        self.spgf = numpy.zeros(shape=(state.itcf_nmax+1, state.system.nbasis,
                                       state.system.nbasis))

    def print_key(self, back_propagation=False, print_function=print, eol=''):
        """Print out information about what the estimates are.

        Parameters
        ----------
        back_propagation : bool, optional
            True if doing back propagation. Default : False.
        print_function : method, optional
            How to print state information, e.g. to std out or file. Default : print.
        eol : string, optional
            String to append to output, e.g., '\n', Default : ''.
        """
        if back_propagation:
            explanation = {
                'iteration': "Simulation iteration when back-propagation "
                             "measurement occured.",
                'E_var': "BP estimate for internal energy.",
                'T': "BP estimate for kinetic energy.",
                'V': "BP estimate for potential energy."
            }
        else:
            explanation = {
                'iteration': "Simulation iteration. iteration*dt = tau.",
                'Weight': "Total walker weight.",
                'E_num': "Numerator for projected energy estimator.",
                'E_denom': "Denominator for projected energy estimator.",
                'E': "Projected energy estimator.",
                'time': "Time per processor to complete one iteration.",
            }
        print_function('# Explanation of output column headers:'+eol)
        print_function('# -------------------------------------'+eol)
        for (k, v) in explanation.items():
            print_function('# %s : %s'%(k, v)+eol)

    def print_header(self, root, header, print_function=print, eol=''):
        """Print out header for estimators

        Parameters
        ----------
        back_propagation : bool, optional
            True if doing back propagation. Default : False.
        print_function : method, optional
            How to print state information, e.g. to std out or file. Default : print.
        eol : string, optional
            String to append to output, e.g., '\n', Default : ''.
        """
        if root:
            print_function(afqmcpy.utils.format_fixed_width_strings(header)+eol)

    def print_step(self, state, comm, step, print_bp=True, print_itcf=True):
        """Print QMC estimates.

        Parameters
        ----------
        state : :class:`afqmcpy.state.State`
            Simulation state.
        comm :
            MPI communicator.
        step : int
            Current iteration number.
        """
        es = self.estimates
        ns = self.names
        es[ns.eproj] = (state.nmeasure*es[ns.enumer]/(state.nprocs*es[ns.edenom])).real
        es[ns.weight:ns.enumer] = es[ns.weight:ns.enumer].real
        es[ns.time] = (time.time()-es[ns.time])/state.nprocs
        es[ns.pot+1:] = self.spgf.flatten()
        global_estimates = numpy.zeros(len(self.estimates))
        comm.Reduce(es, global_estimates, op=MPI.SUM)
        global_estimates[:ns.time] = global_estimates[:ns.time] / state.nmeasure
        if state.root:
            print(afqmcpy.utils.format_fixed_width_floats([step]+
                                                          list(global_estimates[:ns.evar])))
            if state.back_propagation and print_bp:
                ff = afqmcpy.utils.format_fixed_width_floats([step]+
                                                             list(global_estimates[ns.evar:ns.pot+1]/state.nprocs))
                self.funit.write(ff+'\n')
        self.zero(state)

    def print_itcf(self, dt, funit):
        """Save ITCF to file.

        This appends to any previous estimates from the same simulation.

        Stolen from https://stackoverflow.com/a/3685339

        Parameters
        ----------
        itcf : numpy array
            Flattened ITCF.
        dt : float
            Time step
        gf_shape: tuple
            Actual shape of ITCF Green's function matrix.
        funit : file
            Output file for ITCF.
        """
        for (ic, g) in enumerate(self.spgf):
            funit.write(('# tau = %4.2f\n'%(ic*dt)).encode('utf-8'))
            # Maybe look at binary / hdf5 format if things get out of hand.
            numpy.savetxt(funit, g)

    def update(self, w, state):
        """Update estimates for walker w.

        Parameters
        ----------
        w : :class:`afqmcpy.walker.Walker`
            current walker
        state : :class:`afqmcpy.state.State`
            system parameters as well as current 'state' of the simulation.
        """
        if state.importance_sampling:
            # When using importance sampling we only need to know the current
            # walkers weight as well as the local energy, the walker's overlap
            # with the trial wavefunction is not needed.
            if state.cplx:
                self.estimates[self.names.enumer] += w.weight * w.E_L.real
            else:
                self.estimates[self.names.enumer] += w.weight * local_energy(state.system, w.G)[0]
            self.estimates[self.names.weight] += w.weight
            self.estimates[self.names.edenom] += w.weight
        else:
            self.estimates[self.names.enumer] += w.weight * local_energy(state.system, w.G)[0] * w.ot
            self.estimates[self.names.weight] += w.weight
            self.estimates[self.names.edenom] += w.weight * w.ot

    def update_back_propagated_observables(self, system, psi, psit, psib):
        """"Update estimates using back propagated wavefunctions.

        Parameters
        ----------
        state : :class:`afqmcpy.state.State`
            state object
        psi : list of :class:`afqmcpy.walker.Walker` objects
            current distribution of walkers, i.e., at the current iteration in the
            simulation corresponding to :math:`\tau'=\tau+\tau_{bp}`.
        psit : list of :class:`afqmcpy.walker.Walker` objects
            previous distribution of walkers, i.e., at the current iteration in the
            simulation corresponding to :math:`\tau`.
        psib : list of :class:`afqmcpy.walker.Walker` objects
            backpropagated walkers at time :math:`\tau_{bp}`.
        """

        self.estimates[self.names.evar:self.names.pot+1] = back_propagated_energy(system, psi, psit, psib)

    def calculate_itcf(self, state, psi, psi_nm, psi_n, psi_bp):
        """Update estimate for single-particle Green's function.

        Explanation...

        Parameters
        ----------
        system: :class:`afqmcpy.state.System`
            System object.
        psi : list of :class:`afqmcpy.walker.Walker` objects
            current distribution of walkers, i.e., at the current iteration in the
            simulation corresponding to :math:`\tau'=\tau+\tau_{bp}`.
        psit : list of :class:`afqmcpy.walker.Walker` objects
            previous distribution of walkers, i.e., at the current iteration in the
            simulation corresponding to :math:`\tau`.
        psib : list of :class:`afqmcpy.walker.Walker` objects
            backpropagated walkers at time :math:`\tau_{bp}`.
        """
        G = [0, 0]
        I = numpy.identity(state.system.nbasis)
        # I think we need to store the future walker weights when using MPI to
        # average over walkers correctly.
        denominator = sum(w.weight for w in psi_nm)
        for (w, wnm, wt, wb) in zip(psi, psi_nm, psi_n, psi_bp):
            # Loop over walkers
            # Construct back propagated green's function.
            G[0] = I - gab(wb.phi[0], wt.phi[0])
            G[1] = I - gab(wb.phi[1], wt.phi[1])
            self.spgf[0] = self.spgf[0] + wnm.weight*G[0] / denominator
            B = [I, I]
            for (ic, config) in enumerate(w.bp_auxf[:,state.nback_prop:].T):
                # Be simple for the moment. To go further in imaginary time we just
                # need to update the propagation matrix to include more terms of the
                # left.
                # Could optimise this to avoid additional multiplication by GBP.
                Bi = afqmcpy.propagation.construct_propagator_matrix(state, config)
                # B = [Bi[0].dot(B[0]), Bi[1].dot(B[1])]
                G[0] = Bi[0].dot(G[0])
                G[1] = Bi[1].dot(G[1])
                # Only keep up component for the moment.
                # Shouldnt really store these twice, just print them out here.
                self.spgf[ic+1] = self.spgf[ic+1] + wnm.weight*G[0]/denominator
                w.bp_counter = 0

class EstimatorEnum:
    """Enum structure for help with indexing estimators array.

    python's support for enums doesn't help as it indexes from 1.
    """

    def __init__(self, nestimators):
        (self.weight, self.enumer, self.edenom, self.eproj,
         self.time, self.evar, self.kin, self.pot) = range(nestimators)


def local_energy(system, G):
    '''Calculate local energy of walker for the Hubbard model.

Parameters
----------
system : :class:`Hubbard`
    System information for the Hubbard model.
G : :class:`numpy.ndarray`
    Greens function for given walker phi, i.e.,
    :math:`G=\langle \phi_T| c_i^{\dagger}c_j | \phi\rangle`.

Returns
-------
E_L(phi) : float
    Local energy of given walker phi.
'''

    ke = numpy.sum(system.T * (G[0] + G[1]))
    pe = sum(system.U*G[0][i][i]*G[1][i][i] for i in range(0, system.nbasis))

    return (ke + pe, ke, pe)


def back_propagated_energy(system, psi, psit, psib):
    """Calculate back-propagated "local" energy for given walker/determinant.

    Parameters
    ----------
    psi : list of :class:`afqmcpy.walker.Walker` objects
        current distribution of walkers, i.e., at the current iteration in the
        simulation corresponding to :math:`\tau'=\tau+\tau_{bp}`.
    psit : list of :class:`afqmcpy.walker.Walker` objects
        previous distribution of walkers, i.e., at the current iteration in the
        simulation corresponding to :math:`\tau`.
    psib : list of :class:`afqmcpy.walker.Walker` objects
        backpropagated walkers at time :math:`\tau_{bp}`.
    """
    denominator = sum(w.weight for w in psi)
    estimates = numpy.zeros(3)
    GTB = [0, 0]
    for (w, wt, wb) in zip(psi, psit, psib):
        GTB[0] = gab(wb.phi[0], wt.phi[0])
        GTB[1] = gab(wb.phi[1], wt.phi[1])
        estimates = estimates + w.weight*numpy.array(list(local_energy(system, GTB)))
        # print (w.weight, wt.weight, wb.weight, local_energy(system, GTB))
    return estimates / denominator


def gab(A, B):
    r"""One-particle Green's function.

    This actually returns 1-G since it's more useful, i.e.,
    .. math::
        \langle phi_A|c_i^{\dagger}c_j|phi_B\rangle = [B(A^{*T}B)^{-1}A^{*T}]_{ji}

    where :math:`A,B` are the matrices representing the Slater determinants
    :math:`|\psi_{A,B}\rangle`.

    For example, usually A would represent (an element of) the trial wavefunction.

    .. warning::
        Assumes A and B are not orthogonal.

    Parameters
    ----------
    A : :class:`numpy.ndarray`
        Matrix representation of the ket used to construct G.
    B : :class:`numpy.ndarray`
        Matrix representation of the bra used to construct G.

    Returns
    -------
    GAB : :class:`numpy.ndarray`
        (One minus) the green's function.
    """
    inv_O = scipy.linalg.inv((A.conj().T).dot(B))
    GAB = B.dot(inv_O.dot(A.conj().T)).T
    return GAB
