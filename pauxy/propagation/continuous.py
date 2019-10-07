import cmath
import math
import numpy
import sys
from pauxy.propagation.operations import kinetic_real
from pauxy.propagation.hubbard import HubbardContinuous
from pauxy.propagation.planewave import PlaneWave
from pauxy.propagation.generic import GenericContinuous

class Continuous(object):
    """Propagation with continuous HS transformation.
    """
    def __init__(self, system, trial, qmc, options={}, verbose=False):
        if verbose:
            print("# Parsing propagator input options.")
        # Input options
        self.free_projection = options.get('free_projection', False)
        if verbose:
            print("# Using phaseless approximation: %r"%(not self.free_projection))
        self.force_bias = options.get('force_bias', True)
        if self.free_projection:
            if verbose:
                print("# Setting force_bias to False with free projection.")
            self.force_bias = False
        else:
            if verbose:
                print("# Setting force bias to %r."%self.force_bias)
        self.exp_nmax = options.get('expansion_order', 6)
        # Derived Attributes
        self.dt = qmc.dt
        self.sqrt_dt = qmc.dt**0.5
        self.isqrt_dt = 1j*self.sqrt_dt
        # Fix this!
        self.propagator = get_continuous_propagator(system, trial, qmc,
                                                    options=options,
                                                    verbose=verbose)

        # Constant core contribution modified by mean field shift.
        mf_core = self.propagator.mf_core
        self.mf_const_fac = math.exp(-self.dt*mf_core.real)
        self.propagator.construct_one_body_propagator(system, qmc.dt)
        self.BT_BP = self.propagator.BH1
        self.nstblz = qmc.nstblz
        self.nfb_trig = 0
        self.nhe_trig = 0


        self.ebound = (2.0/self.dt)**0.5
        self.mean_local_energy = 0

        if self.free_projection:
            if verbose:
                print("# Using free projection.")
            self.propagate_walker = self.propagate_walker_free
        else:
            if verbose:
                print("# Using phaseless approximation.")
            self.propagate_walker = self.propagate_walker_phaseless
        self.verbose = verbose

    def apply_exponential(self, phi, VHS, debug=False):
        """Apply exponential propagator of the HS transformation
        Parameters
        ----------
        system :
            system class
        phi : numpy array
            a state
        VHS : numpy array
            HS transformation potential
        Returns
        -------
        phi : numpy array
            Exp(VHS) * phi
        """
        # JOONHO: exact exponential
        # copy = numpy.copy(phi)
        # phi = scipy.linalg.expm(VHS).dot(copy)
        if debug:
            copy = numpy.copy(phi)
            c2 = scipy.linalg.expm(VHS).dot(copy)
        # Temporary array for matrix exponentiation.
        Temp = numpy.zeros(phi.shape, dtype=phi.dtype)

        numpy.copyto(Temp, phi)
        for n in range(1, self.exp_nmax+1):
            Temp = VHS.dot(Temp) / n
            phi += Temp
        if debug:
            print("DIFF: {: 10.8e}".format((c2 - phi).sum() / c2.size))
        return phi

    def two_body_propagator(self, walker, system, trial):
        """It appliese the two-body propagator
        Parameters
        ----------
        walker :
            walker class
        system :
            system class
        fb : boolean
            wheter to use force bias
        Returns
        -------
        cxf : float
            the constant factor arises from mean-field shift (hard-coded for UEG for now)
        cfb : float
            the constant factor arises from the force-bias
        xshifted : numpy array
            shifited auxiliary field
        """
        # Normally distrubted auxiliary fields.
        xi = numpy.random.normal(0.0, 1.0, system.nfields)

        # Optimal force bias.
        xbar = numpy.zeros(system.nfields)
        if self.force_bias:
            xbar = self.propagator.construct_force_bias(system, walker, trial)

        for i in range(system.nfields):
            if numpy.absolute(xbar[i]) > 1.0:
                if self.nfb_trig < 1:
                    if self.verbose:
                        pass
                        # TODO: Fix verbosity setting. We broadcast the qmc
                        # object.
                        # print("# Rescaling force bias is triggered: {} {}"
                              # .format(xbar[i], 1.0))
                        # print("# Warning will only be printed once.")
                self.nfb_trig += 1
                xbar[i] /= numpy.absolute(xbar[i])

        xshifted = xi - xbar

        # Constant factor arising from force bias and mean field shift
        cmf = -self.sqrt_dt * xshifted.dot(self.propagator.mf_shift)
        # Constant factor arising from shifting the propability distribution.
        cfb = xi.dot(xbar) - 0.5*xbar.dot(xbar)

        # Operator terms contributing to propagator.
        VHS = self.propagator.construct_VHS(system, xshifted)

        # Apply propagator
        self.apply_exponential(walker.phi[:,:system.nup], VHS)
        if system.ndown > 0:
            self.apply_exponential(walker.phi[:,system.nup:], VHS)

        return (cmf, cfb, xshifted)

    def propagate_walker_free(self, walker, system, trial, eshift):
        """Free projection propagator
        Parameters
        ----------
        walker :
            walker class
        system :
            system class
        trial :
            trial wavefunction class
        Returns
        -------
        """
        # 1. Apply kinetic projector.
        kinetic_real(walker.phi, system, self.propagator.BH1)
        # 2. Apply 2-body projector
        (cmf, cfb, xmxbar) = self.two_body_propagator(walker, system, trial)
        # 3. Apply kinetic projector.
        kinetic_real(walker.phi, system, self.propagator.BH1)
        walker.inverse_overlap(trial)
        walker.ot = walker.calc_otrial(trial)
        walker.greens_function(trial)
        # Constant terms are included in the walker's weight.
        (magn, dtheta) = cmath.polar(cmath.exp(cmf+self.dt*eshift))
        walker.weight *= magn
        walker.phase *= cmath.exp(1j*dtheta)

    def apply_bound(self, ehyb, eshift):
        if ehyb.real > eshift.real + self.ebound:
            ehyb = eshift.real+self.ebound+1j*ehyb.imag
            self.nhe_trig += 1
        elif ehyb.real < eshift.real - self.ebound:
            ehyb = eshift.real-self.ebound+1j*ehyb.imag
            self.nhe_trig += 1
        return ehyb

    def propagate_walker_phaseless(self, walker, system, trial, eshift):
        """Phaseless propagator
        Parameters
        ----------
        walker :
            walker class
        system :
            system class
        trial :
            trial wavefunction class
        Returns
        -------
        """
        # 1. Apply one_body propagator.
        kinetic_real(walker.phi, system, self.propagator.BH1)
        # 2. Apply two_body propagator.
        (cmf, cfb, xmxbar) = self.two_body_propagator(walker, system, trial)
        # 3. Apply one_body propagator.
        kinetic_real(walker.phi, system, self.propagator.BH1)

        # Now apply hybrid phaseless approximation
        walker.inverse_overlap(trial)
        walker.greens_function(trial)
        ot_new = walker.calc_otrial(trial)
        ovlp_ratio = ot_new / walker.ot
        hybrid_energy = -(cmath.log(ovlp_ratio) + cfb + cmf)/self.dt
        hybrid_energy = self.apply_bound(hybrid_energy, eshift)
        importance_function = (
                self.mf_const_fac *
                cmath.exp(-self.dt*(0.5*(hybrid_energy+walker.hybrid_energy)-eshift))
        )
        # splitting w_alpha = |I(x,\bar{x},|phi_alpha>)| e^{i theta_alpha}
        (magn, phase) = cmath.polar(importance_function)
        walker.hybrid_energy = hybrid_energy

        if not math.isinf(magn):
            # Determine cosine phase from Arg(<psi_T|B(x-\bar{x})|phi>/<psi_T|phi>)
            # Note this doesn't include exponential factor from shifting
            # propability distribution.
            dtheta = (-self.dt*hybrid_energy-cfb).imag
            cosine_fac = max(0, math.cos(dtheta))
            walker.weight *= magn * cosine_fac
            walker.ot = ot_new
            if magn > 1e-16:
                wfac = numpy.array([importance_function/magn, cosine_fac])
            else:
                wfac = numpy.array([0,0])
            try:
                walker.field_configs.update(xmxbar, wfac)
            except AttributeError:
                pass
        else:
            walker.ot = ot_new
            walker.weight = 0.0

def get_continuous_propagator(system, trial, qmc, options={}, verbose=False):
    """Wrapper to select propagator class.

    Parameters
    ----------
    options : dict
        Propagator input options.
    qmc : :class:`pauxy.qmc.QMCOpts` class
        Trial wavefunction input options.
    system : class
        System class.
    trial : class
        Trial wavefunction object.

    Returns
    -------
    propagator : class or None
        Propagator object.
    """
    if system.name == "UEG":
        propagator = PlaneWave(system, trial, qmc,
                               options=options,
                               verbose=verbose)
    elif system.name == "Hubbard":
        propagator = HubbardContinuous(system, trial, qmc,
                                       options=options,
                                       verbose=verbose)
    elif system.name == "Generic":
        propagator = GenericContinuous(system, trial, qmc,
                                       options=options,
                                       verbose=verbose)
    else:
        propagator = None

    return propagator


def unit_test():
    from pauxy.systems.ueg import UEG
    from pauxy.qmc.options import QMCOpts
    from pauxy.trial_wavefunction.hartree_fock import HartreeFock

    inputs = {'nup':1, 'ndown':1,
    'rs':1.0, 'ecut':1.0, 'dt':0.05, 'nwalkers':10}

    system = UEG(inputs, True)

    qmc = QMCOpts(inputs, system, True)

    trial = HartreeFock(system, False, inputs, True)

    driver = Continuous({}, qmc, system, trial, True)
