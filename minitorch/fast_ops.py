from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, Any

import numpy as np
from numba import prange
from numba import njit as _njit


from .tensor_data import (
    broadcast_index,
    index_to_position,
    shape_broadcast,
    to_index,
)
from .tensor_ops import MapProto, TensorOps

if TYPE_CHECKING:
    from typing import Callable, Optional

    from .tensor import Tensor
    from .tensor_data import Shape, Storage, Strides

# TIP: Use `NUMBA_DISABLE_JIT=1 pytest tests/ -m task3_1` to run these tests without JIT.

# This code will JIT compile fast versions your tensor_data functions.
# If you get an error, read the docs for NUMBA as to what is allowed
# in these functions.
Fn = TypeVar("Fn")


def njit(fn: Fn, **kwargs: Any) -> Fn:
    """Numba jit decorator."""
    return _njit(inline="always", **kwargs)(fn)  # type: ignore


to_index = njit(to_index)
index_to_position = njit(index_to_position)
broadcast_index = njit(broadcast_index)


class FastOps(TensorOps):
    @staticmethod
    def map(fn: Callable[[float], float]) -> MapProto:
        """See `tensor_ops.py`"""
        # This line JIT compiles your tensor_map
        f = tensor_map(njit(fn))

        def ret(a: Tensor, out: Optional[Tensor] = None) -> Tensor:
            if out is None:
                out = a.zeros(a.shape)
            f(*out.tuple(), *a.tuple())
            return out

        return ret

    @staticmethod
    def zip(fn: Callable[[float, float], float]) -> Callable[[Tensor, Tensor], Tensor]:
        """See `tensor_ops.py`"""
        f = tensor_zip(njit(fn))

        def ret(a: Tensor, b: Tensor) -> Tensor:
            c_shape = shape_broadcast(a.shape, b.shape)
            out = a.zeros(c_shape)
            f(*out.tuple(), *a.tuple(), *b.tuple())
            return out

        return ret

    @staticmethod
    def reduce(
        fn: Callable[[float, float], float], start: float = 0.0
    ) -> Callable[[Tensor, int], Tensor]:
        """See `tensor_ops.py`"""
        f = tensor_reduce(njit(fn))

        def ret(a: Tensor, dim: int) -> Tensor:
            out_shape = list(a.shape)
            out_shape[dim] = 1

            # Other values when not sum.
            out = a.zeros(tuple(out_shape))
            out._tensor._storage[:] = start

            f(*out.tuple(), *a.tuple(), dim)
            return out

        return ret

    @staticmethod
    def matrix_multiply(a: Tensor, b: Tensor) -> Tensor:
        """Batched tensor matrix multiply ::

            for n:
              for i:
                for j:
                  for k:
                    out[n, i, j] += a[n, i, k] * b[n, k, j]

        Where n indicates an optional broadcasted batched dimension.

        Should work for tensor shapes of 3 dims ::

            assert a.shape[-1] == b.shape[-2]

        Args:
        ----
            a : tensor data a
            b : tensor data b

        Returns:
        -------
            New tensor data

        """
        # Make these always be a 3 dimensional multiply
        both_2d = 0
        if len(a.shape) == 2:
            a = a.contiguous().view(1, a.shape[0], a.shape[1])
            both_2d += 1
        if len(b.shape) == 2:
            b = b.contiguous().view(1, b.shape[0], b.shape[1])
            both_2d += 1
        both_2d = both_2d == 2

        ls = list(shape_broadcast(a.shape[:-2], b.shape[:-2]))
        ls.append(a.shape[-2])
        ls.append(b.shape[-1])
        assert a.shape[-1] == b.shape[-2]
        out = a.zeros(tuple(ls))

        tensor_matrix_multiply(*out.tuple(), *a.tuple(), *b.tuple())

        # Undo 3d if we added it.
        if both_2d:
            out = out.view(out.shape[1], out.shape[2])
        return out


# Implementations


def tensor_map(
    fn: Callable[[float], float],
) -> Callable[[Storage, Shape, Strides, Storage, Shape, Strides], None]:
    """NUMBA low_level tensor_map function. See `tensor_ops.py` for description.

    Optimizations:

    * Main loop in parallel
    * All indices use numpy buffers
    * When `out` and `in` are stride-aligned, avoid indexing

    Args:
    ----
        fn: function mappings floats-to-floats to apply.

    Returns:
    -------
        Tensor map function.

    """

    def _map(
        out: Storage,
        out_shape: Shape,
        out_strides: Strides,
        in_storage: Storage,
        in_shape: Shape,
        in_strides: Strides,
    ) -> None:
        # TODO: Implement for Task 3.1.
        # Check if tensors are stride-aligned
        # Check for aligned tensors
        is_aligned = (
            len(out_strides) == len(in_strides)
            and np.array_equal(out_strides, in_strides)
            and np.array_equal(out_shape, in_shape)
        )

        if is_aligned:
            # Fast path for aligned tensors
            for idx in prange(len(out)):
                out[idx] = fn(in_storage[idx])
            return

        # Calculate total elements in output
        total_elements = np.prod(out_shape)

        # Main parallel processing loop
        for i in prange(total_elements):
            # Create index buffers per thread
            out_index = np.empty(len(out_shape), np.int32)
            in_index = np.empty(len(in_shape), np.int32)
            # Convert position to indices
            to_index(i, out_shape, out_index)
            # Calculate output position
            o_pos = index_to_position(out_index, out_strides)
            # Map output index to input index
            broadcast_index(out_index, out_shape, in_shape, in_index)
            # Calculate input position
            i_pos = index_to_position(in_index, in_strides)
            # Apply function
            out[o_pos] = fn(in_storage[i_pos])

    return njit(_map, parallel=True)


def tensor_zip(
    fn: Callable[[float, float], float],
) -> Callable[
    [Storage, Shape, Strides, Storage, Shape, Strides, Storage, Shape, Strides], None
]:
    """NUMBA higher-order tensor zip function. See `tensor_ops.py` for description.

    Optimizations:

    * Main loop in parallel
    * All indices use numpy buffers
    * When `out`, `a`, `b` are stride-aligned, avoid indexing

    Args:
    ----
        fn: function maps two floats to float to apply.

    Returns:
    -------
        Tensor zip function.

    """

    def _zip(
        out: Storage,
        out_shape: Shape,
        out_strides: Strides,
        a_storage: Storage,
        a_shape: Shape,
        a_strides: Strides,
        b_storage: Storage,
        b_shape: Shape,
        b_strides: Strides,
    ) -> None:
        # Special case - when tensors are stride-aligned, avoid indexing
        # Check if tensors are stride-aligned
        if (
            len(out_strides) == len(a_strides) == len(b_strides)
            and np.array_equal(out_strides, a_strides)
            and np.array_equal(out_strides, b_strides)
            and np.array_equal(out_shape, a_shape)
            and np.array_equal(out_shape, b_shape)
        ):
            # Optimized path for stride-aligned tensors
            for idx in prange(len(out)):
                out[idx] = fn(a_storage[idx], b_storage[idx])
            return

        # Handle tensors with non-aligned strides
        total_elements = 1
        for dim_size in out_shape:
            total_elements *= dim_size

        for i in prange(total_elements):
            # Create index buffers per thread
            out_index = np.empty(len(out_shape), np.int32)
            a_index = np.empty(len(out_shape), np.int32)
            b_index = np.empty(len(out_shape), np.int32)
            # Convert position to indices and calculate positions
            to_index(i, out_shape, out_index)
            o_pos = index_to_position(out_index, out_strides)
            broadcast_index(out_index, out_shape, a_shape, a_index)
            a_pos = index_to_position(a_index, a_strides)
            broadcast_index(out_index, out_shape, b_shape, b_index)
            b_pos = index_to_position(b_index, b_strides)
            out[o_pos] = fn(a_storage[a_pos], b_storage[b_pos])

    return njit(_zip, parallel=True)


def tensor_reduce(
    fn: Callable[[float, float], float],
) -> Callable[[Storage, Shape, Strides, Storage, Shape, Strides, int], None]:
    """NUMBA higher-order tensor reduce function. See `tensor_ops.py` for description.

    Optimizations:

    * Main loop in parallel
    * All indices use numpy buffers
    * Inner-loop should not call any functions or write non-local variables

    Args:
    ----
        fn: reduction function mapping two floats to float.

    Returns:
    -------
        Tensor reduce function

    """

    def _reduce(
        out: Storage,
        out_shape: Shape,
        out_strides: Strides,
        a_storage: Storage,
        a_shape: Shape,
        a_strides: Strides,
        reduce_dim: int,
    ) -> None:
        # Calculate output size
        size = len(out_shape)
        out_size = 1
        for i in range(size):
            out_size *= out_shape[i]

        # Main parallel loop over output positions
        for i in prange(out_size):
            # Create thread-local index buffers
            out_index = np.empty(size, np.int32)
            a_index = np.empty(size, np.int32)

            # Convert position to indices
            to_index(i, out_shape, out_index)

            # Calculate output position
            o_pos = index_to_position(out_index, out_strides)

            # Copy output index to a_index
            for j in range(size):
                a_index[j] = out_index[j]

            # Initialize reduction with first element
            a_index[reduce_dim] = 0
            pos = index_to_position(a_index, a_strides)
            reduced = a_storage[pos]

            # Inner reduction loop starting from second element
            for j in range(1, a_shape[reduce_dim]):
                a_index[reduce_dim] = j
                pos = index_to_position(a_index, a_strides)
                # Apply reduction function
                reduced = fn(reduced, a_storage[pos])

            # Store result
            out[o_pos] = reduced

    return njit(_reduce, parallel=True)


def _tensor_matrix_multiply(
    out: Storage,
    out_shape: Shape,
    out_strides: Strides,
    a_storage: Storage,
    a_shape: Shape,
    a_strides: Strides,
    b_storage: Storage,
    b_shape: Shape,
    b_strides: Strides,
) -> None:
    """NUMBA tensor matrix multiply function.

    Should work for any tensor shapes that broadcast as long as

    ```
    assert a_shape[-1] == b_shape[-2]
    ```

    Optimizations:

    * Outer loop in parallel
    * No index buffers or function calls
    * Inner loop should have no global writes, 1 multiply.


    Args:
    ----
        out (Storage): storage for `out` tensor
        out_shape (Shape): shape for `out` tensor
        out_strides (Strides): strides for `out` tensor
        a_storage (Storage): storage for `a` tensor
        a_shape (Shape): shape for `a` tensor
        a_strides (Strides): strides for `a` tensor
        b_storage (Storage): storage for `b` tensor
        b_shape (Shape): shape for `b` tensor
        b_strides (Strides): strides for `b` tensor

    Returns:
    -------
        None : Fills in `out`

    """
    a_batch_stride = a_strides[0] if a_shape[0] > 1 else 0
    b_batch_stride = b_strides[0] if b_shape[0] > 1 else 0

    # TODO: Implement for Task 3.2.
    for i in prange(out_shape[0]):
        for j in range(out_shape[1]):
            for k in range(out_shape[2]):
                # Initialize accumulator for dot product
                acc = 0.0
                # Compute dot product along shared dimension
                for l in range(a_shape[-1]):
                    # Get positions in a and b storage
                    a_pos = i * a_batch_stride + j * a_strides[1] + l * a_strides[2]
                    b_pos = i * b_batch_stride + l * b_strides[1] + k * b_strides[2]
                    # Multiply and accumulate
                    acc += a_storage[a_pos] * b_storage[b_pos]
                # Write result to output
                out_pos = i * out_strides[0] + j * out_strides[1] + k * out_strides[2]
                out[out_pos] = acc


tensor_matrix_multiply = njit(_tensor_matrix_multiply, parallel=True)
assert tensor_matrix_multiply is not None
