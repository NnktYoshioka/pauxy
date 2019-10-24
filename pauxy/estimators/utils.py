import h5py
try:
    import pyfftw
except ImportError:
    pass
import numpy
import scipy
from scipy.fftpack.helper import next_fast_len
from scipy.fftpack.helper import _init_nd_shape_and_axes_sorted

# Stolen from scipy
def scipy_fftconvolve(in1, in2, mesh1 = None, mesh2 = None, mode="full", axes=None):
    """Convolve two N-dimensional arrays using FFT.
    Convolve `in1` and `in2` using the fast Fourier transform method, with
    the output size determined by the `mode` argument.
    This is generally much faster than `convolve` for large arrays (n > ~500),
    but can be slower when only a few output values are needed, and can only
    output float arrays (int or object array inputs will be cast to float).
    As of v0.19, `convolve` automatically chooses this method or the direct
    method based on an estimation of which is faster.
    Parameters
    ----------
    in1 : array_like
        First input.
    in2 : array_like
        Second input. Should have the same number of dimensions as `in1`.
    mode : str {'full', 'valid', 'same'}, optional
        A string indicating the size of the output:
        ``full``
           The output is the full discrete linear convolution
           of the inputs. (Default)
        ``valid``
           The output consists only of those elements that do not
           rely on the zero-padding. In 'valid' mode, either `in1` or `in2`
           must be at least as large as the other in every dimension.
        ``same``
           The output is the same size as `in1`, centered
           with respect to the 'full' output.
           axis : tuple, optional
    axes : int or array_like of ints or None, optional
        Axes over which to compute the convolution.
        The default is over all axes.
    Returns
    -------
    out : array
        An N-dimensional array containing a subset of the discrete linear
        convolution of `in1` with `in2`.
    """

    if (not mesh1 == None):
        in1 = in1.reshape(mesh1)
    if (not mesh2 == None):
        in2 = in2.reshape(mesh2)

    in1 = numpy.asarray(in1)
    in2 = numpy.asarray(in2)
    noaxes = axes is None

    if in1.ndim == in2.ndim == 0:  # scalar inputs
        return in1 * in2
    elif in1.ndim != in2.ndim:
        raise ValueError("in1 and in2 should have the same dimensionality")
    elif in1.size == 0 or in2.size == 0:  # empty arrays
        return numpy.array([])

    _, axes = _init_nd_shape_and_axes_sorted(in1, shape=None, axes=axes)

    if not noaxes and not axes.size:
        raise ValueError("when provided, axes cannot be empty")

    if noaxes:
        other_axes = numpy.array([], dtype=numpy.intc)
    else:
        other_axes = numpy.setdiff1d(numpy.arange(in1.ndim), axes)

    s1 = numpy.array(in1.shape)
    s2 = numpy.array(in2.shape)

    if not numpy.all((s1[other_axes] == s2[other_axes])
                  | (s1[other_axes] == 1) | (s2[other_axes] == 1)):
        raise ValueError("incompatible shapes for in1 and in2:"
                         " {0} and {1}".format(in1.shape, in2.shape))

    complex_result = (numpy.issubdtype(in1.dtype, numpy.complexfloating)
                      or numpy.issubdtype(in2.dtype, numpy.complexfloating))
    shape = numpy.maximum(s1, s2)
    shape[axes] = s1[axes] + s2[axes] - 1

    # Check that input sizes are compatible with 'valid' mode
    if scipy.signal.signaltools._inputs_swap_needed(mode, s1, s2):
        # Convolution is commutative; order doesn't have any effect on output
        in1, s1, in2, s2 = in2, s2, in1, s1

    # Speed up FFT by padding to optimal size for FFTPACK
    fshape = [next_fast_len(d) for d in shape[axes]]
    fslice = tuple([slice(sz) for sz in shape])
    
    # Pre-1.9 NumPy FFT routines are not threadsafe.  For older NumPys, make
    # sure we only call rfftn/irfftn from one thread at a time.

    # If we're here, it's either because we need a complex result, or we
    # failed to acquire _rfft_lock (meaning rfftn isn't threadsafe and
    # is already in use by another thread).  In either case, use the
    # (threadsafe but slower) SciPy complex-FFT routines instead.
    sp1 = numpy.fft.fftn(in1, fshape, axes=axes)
    sp2 = numpy.fft.fftn(in2, fshape, axes=axes)
    ret = numpy.fft.ifftn(sp1 * sp2, axes=axes)[fslice].copy()

    if not complex_result:
        ret = ret.real

    if mode == "full":
        return ret
    elif mode == "same":
        return scipy.signal.signaltools._centered(ret, s1)
    elif mode == "valid":
        shape_valid = shape.copy()
        shape_valid[axes] = s1[axes] - s2[axes] + 1
        return scipy.signal.signaltools._centered(ret, shape_valid)
    else:
        raise ValueError("acceptable mode flags are 'valid',"
                         " 'same', or 'full'")


def convolve(f, g, mesh, backend=numpy.fft):
    f_ = f.reshape(*mesh)
    g_ = g.reshape(*mesh)
    shape = numpy.maximum(f_.shape, g_.shape)
    min_shape = numpy.array(f_.shape) + numpy.array(g_.shape) - 1

    nqtot = numpy.prod(min_shape)
    fshape = [next_fast_len(d) for d in min_shape]

    finv = backend.ifftn(f_, s=fshape)
    ginv = backend.ifftn(g_, s=fshape)
    fginv = finv * ginv
    fq = backend.fftn(fginv).copy().ravel()
    fq = fq.reshape(fshape)
    fq = fq[:min_shape[0],:min_shape[1],:min_shape[2]]
    fq = fq.reshape(nqtot) * numpy.prod(fshape)
    return fq

class H5EstimatorHelper(object):
    """Helper class for pushing data to hdf5 dataset of fixed length.

    Parameters
    ----------
    h5f : :class:`h5py.File`
        Output file object.
    name : string
        Dataset name.
    shape : tuple
        Shape of output data.
    dtype : type
        Output data type.

    Attributes
    ----------
    store : :class:`h5py.File.DataSet`
        Dataset object.
    index : int
        Counter for incrementing data.
    """
    def __init__(self, filename, base):
        # self.store = h5f.create_dataset(name, shape, dtype=dtype)
        self.filename = filename
        self.base = base
        self.index = 0
        self.nzero = 9

    def push(self, data, name):
        """Push data to dataset.

        Parameters
        ----------
        data : :class:`numpy.ndarray`
            Data to push.
        """
        ix = str(self.index)
        # To ensure string indices are sorted properly.
        padded = '0'*(self.nzero-len(ix)) + ix
        dset = self.base + '/' + name + '/' + padded
        with h5py.File(self.filename, 'a') as fh5:
            fh5[dset] = data

    def increment(self):
        self.index = self.index + 1

    def reset(self):
        self.index = 0
