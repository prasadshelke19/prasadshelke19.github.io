"""The public mirror reader must preserve exact scientific array values."""
from pathlib import Path
import sys
import struct
import numpy as np
import pytest
from numcodecs import Blosc
sys.path.insert(0, str(Path(__file__).parents[1] / "pipeline"))
from download_arco import blosc_slice, TransferBudget


@pytest.mark.parametrize("clevel,shuffle", [(5, 1), (5, 0), (0, 0)])
def test_selective_blosc_decode_is_exact_across_block_boundaries(clevel, shuffle):
    values = np.random.default_rng(1).normal(53000, 1500, (8, 32, 64)).astype("<f4")
    raw = values.tobytes()
    packed = Blosc(cname="lz4", clevel=clevel, shuffle=shuffle, blocksize=2048).encode(values)
    calls = []
    def read_range(a, b):
        calls.append((a, b))
        return packed[a:b + 1]
    offset, length = 3 * 32 * 64 * 4 + 12, 32 * 64 * 4 - 24
    assert blosc_slice(read_range, len(raw), offset, length) == raw[offset:offset + length]
    assert sum(b - a + 1 for a, b in calls) <= len(packed)


def test_physical_block_order_need_not_match_logical_order():
    values = (53000 + 100*np.sin(np.arange(262144)/30)).astype("<f4")
    raw = values.tobytes()
    packed = Blosc(cname="lz4", clevel=5, shuffle=1, blocksize=2048).encode(values)
    assert not packed[2] & 2  # This fixture must exercise compressed blocks.
    nbytes, blocksize, cbytes = struct.unpack("<III", packed[4:16])
    nblocks = (nbytes + blocksize - 1) // blocksize
    assert nblocks > 2
    index = list(struct.unpack("<" + "I" * nblocks, packed[16:16 + 4*nblocks]))
    physical = sorted(index)
    ends = dict(zip(physical, physical[1:] + [cbytes]))
    order = list(reversed(range(nblocks)))
    pieces, new_index, cursor = [], [0] * nblocks, 16 + 4 * nblocks
    for i in order:
        piece = packed[index[i]:ends[index[i]]]
        new_index[i] = cursor
        pieces.append(piece)
        cursor += len(piece)
    reordered = packed[:16] + struct.pack("<" + "I" * nblocks, *new_index) + b"".join(pieces)
    assert Blosc().decode(reordered) == raw
    assert blosc_slice(lambda a, b: reordered[a:b+1], len(raw), 3*2048+100, 5000) == raw[3*2048+100:3*2048+5100]


def test_changed_chunk_dimensions_are_rejected():
    raw = np.zeros(16384, dtype="<f4").tobytes()
    packed = Blosc(cname="lz4", blocksize=2048).encode(raw)
    with pytest.raises(ValueError, match="shape"):
        blosc_slice(lambda a, b: packed[a:b+1], len(raw) + 4, 0, 100)


def test_transfer_budget_rejects_an_oversized_request_before_network_access():
    budget = TransferBudget(.001)
    budget.reserve(900)
    with pytest.raises(ValueError, match="budget"):
        budget.reserve(101)
    assert budget.reserved == 900
