import pytest
from hypothesis import given

import minitorch
from minitorch import Tensor

from .strategies import assert_close
from .tensor_strategies import tensors


@pytest.mark.task4_3
@given(tensors(shape=(1, 1, 4, 4)))
def test_avg(t: Tensor) -> None:
    out = minitorch.avgpool2d(t, (2, 2))
    assert_close(
        out[0, 0, 0, 0], sum([t[0, 0, i, j] for i in range(2) for j in range(2)]) / 4.0
    )

    out = minitorch.avgpool2d(t, (2, 1))
    assert_close(
        out[0, 0, 0, 0], sum([t[0, 0, i, j] for i in range(2) for j in range(1)]) / 2.0
    )

    out = minitorch.avgpool2d(t, (1, 2))
    assert_close(
        out[0, 0, 0, 0], sum([t[0, 0, i, j] for i in range(1) for j in range(2)]) / 2.0
    )
    minitorch.grad_check(lambda t: minitorch.avgpool2d(t, (2, 2)), t)


@pytest.mark.task4_4
@given(tensors(shape=(2, 3, 4)))
def test_max(t: Tensor) -> None:
    # Test max along different dimensions
    out = minitorch.max(t, 2)  # Max along last dimension
    assert out.shape == (2, 3, 1)
    for i in range(2):
        for j in range(3):
            assert_close(out[i, j, 0], max([t[i, j, k] for k in range(4)]))

    out = minitorch.max(t, 1)  # Max along middle dimension
    assert out.shape == (2, 1, 4)
    for i in range(2):
        for j in range(4):
            assert_close(out[i, 0, j], max([t[i, k, j] for k in range(3)]))

    out = minitorch.max(t, 0)  # Max along first dimension
    assert out.shape == (1, 3, 4)
    for i in range(3):
        for j in range(4):
            assert_close(out[0, i, j], max([t[k, i, j] for k in range(2)]))


@pytest.mark.task4_4
@given(tensors(shape=(2, 3, 4)))
def test_softmax_properties(t: Tensor) -> None:
    """Test additional softmax properties."""
    # Test that softmax sums to 1 along any dimension
    for dim in range(3):
        s = minitorch.softmax(t, dim=dim)
        sums = s.sum(dim=dim)
        for idx in sums._tensor.indices():
            assert_close(sums[idx], 1.0)

    # Test that softmax is between 0 and 1
    s = minitorch.softmax(t, dim=1)
    for idx in s._tensor.indices():
        assert 0 <= s[idx] <= 1

    # Test that max value gets highest probability
    dim = 2
    s = minitorch.softmax(t, dim=dim)
    for i in range(2):
        for j in range(3):
            max_idx = max(range(4), key=lambda k: t[i, j, k])
            assert_close(s[i, j, max_idx], max([s[i, j, k] for k in range(4)]))


@pytest.mark.task4_4
@given(tensors(shape=(1, 1, 4, 4)))
def test_log_softmax(t: Tensor) -> None:
    q = minitorch.softmax(t, 3)
    q2 = minitorch.logsoftmax(t, 3).exp()
    for i in q._tensor.indices():
        assert_close(q[i], q2[i])

    minitorch.grad_check(lambda a: minitorch.logsoftmax(a, dim=2), t)


@pytest.mark.task4_4
@given(tensors())
def test_dropout_rate(t: Tensor) -> None:
    q = minitorch.dropout(t, 0.0)
    idx = q._tensor.sample()
    assert q[idx] == t[idx]
    q = minitorch.dropout(t, 1.0)
    assert q[q._tensor.sample()] == 0.0
    q = minitorch.dropout(t, 1.0, ignore=True)
    idx = q._tensor.sample()
    assert q[idx] == t[idx]


@pytest.mark.task4_4
@given(tensors(shape=(1, 1, 4, 4)))
def test_max_pool_2d(t: Tensor) -> None:
    out = minitorch.maxpool2d(t, (2, 2))
    print(out)
    print(t)
    assert_close(
        out[0, 0, 0, 0], max([t[0, 0, i, j] for i in range(2) for j in range(2)])
    )

    out = minitorch.maxpool2d(t, (2, 1))
    assert_close(
        out[0, 0, 0, 0], max([t[0, 0, i, j] for i in range(2) for j in range(1)])
    )

    out = minitorch.maxpool2d(t, (1, 2))
    assert_close(
        out[0, 0, 0, 0], max([t[0, 0, i, j] for i in range(1) for j in range(2)])
    )


@pytest.mark.task4_4
@given(tensors(shape=(1, 1, 4, 4)))
def test_softmax(t: Tensor) -> None:
    q = minitorch.softmax(t, 3)
    x = q.sum(dim=3)
    assert_close(x[0, 0, 0, 0], 1.0)

    q = minitorch.softmax(t, 1)
    x = q.sum(dim=1)
    assert_close(x[0, 0, 0, 0], 1.0)

    minitorch.grad_check(lambda a: minitorch.softmax(a, dim=2), t)


@pytest.mark.task4_4
@given(tensors(shape=(1, 1, 4, 4)))
def test_log_softmax_2d(t: Tensor) -> None:
    q = minitorch.softmax(t, 3)
    q2 = minitorch.logsoftmax(t, 3).exp()
    for i in q._tensor.indices():
        assert_close(q[i], q2[i])

    minitorch.grad_check(lambda a: minitorch.logsoftmax(a, dim=2), t)
