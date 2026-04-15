"""Double-elimination bracket generation invariants (arbitrary n >= 8).

Losers *layers* vs winners *layers* (this codebase):
  L = 2 * W - 2   where W = len(winners_layer_sizes), L = len(l_round_sizes).

So losers has *more* horizontal rounds than winners for W >= 3 (e.g. W=4 → L=6).
That is expected for this schedule: each winners wave plus merge/shelf rounds adds
losers depth. It is *not* generally "one fewer losers round than winners"; odd n
does not change the formula — only w_r1 and the halving tree matter.
"""
import pytest
from sqlalchemy import select

from bot.models import BracketMatch, Tournament
from bot.models.base import async_session_factory
from bot.services.bracket_gen import (
    _double_elim_loser_round_sizes,
    _losers_wb_injection_dest_layers,
    _winners_layer_sizes,
    preview_bracket_structure,
    _create_double_elim_matches,
    flush_double_elim_after_score_update,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "n",
    list(range(8, 25)) + [32, 48],
)
async def test_double_elim_all_wb_nonfinal_have_loser_drop(n):
    """Every winners match except the final has loser_advances_to_* set; targets are unique per slot."""
    async with async_session_factory() as session:
        t = Tournament(guild_id=1, name=f"de-{n}", format="1v1", mmr_playlist="solo_duel")
        session.add(t)
        await session.flush()
        seeded = [(i, False, False) for i in range(n)]
        bracket = await _create_double_elim_matches(session, t.id, seeded, False)
        assert bracket is not None

        r = await session.execute(
            select(BracketMatch).where(BracketMatch.bracket_id == bracket.id)
        )
        matches = r.scalars().all()
        w = [m for m in matches if m.bracket_section == "winners"]
        w_final = w[-1]
        targets: set[tuple[int, int]] = set()
        for m in w:
            if m.id == w_final.id:
                continue
            assert m.loser_advances_to_match_id is not None
            assert m.loser_advances_to_slot in (1, 2)
            key = (m.loser_advances_to_match_id, m.loser_advances_to_slot)
            assert key not in targets, f"duplicate WB loser target {key} for n={n}"
            targets.add(key)


@pytest.mark.asyncio
async def test_double_elim_losers_merge_after_wb_round():
    """After the 2-match WB-drop losers round, the next round is a single merge (not another 2)."""
    async with async_session_factory() as session:
        t = Tournament(guild_id=1, name="de-12", format="1v1", mmr_playlist="solo_duel")
        session.add(t)
        await session.flush()
        n = 12
        seeded = [(i, False, False) for i in range(n)]
        bracket = await _create_double_elim_matches(session, t.id, seeded, False)
        assert bracket is not None
        r = await session.execute(
            select(BracketMatch).where(BracketMatch.bracket_id == bracket.id)
        )
        matches = r.scalars().all()
        losers = [m for m in matches if m.bracket_section == "losers"]
        by_round: dict[int, list] = {}
        for m in losers:
            by_round.setdefault(m.round_num, []).append(m)
        w_r1 = (n + 1) // 2
        l_r1 = (w_r1 + 1) // 2
        w_layers = _winners_layer_sizes(w_r1)
        layers = _double_elim_loser_round_sizes(l_r1, w_layers)
        assert len(layers) == len(by_round)
        for i, sz in enumerate(layers):
            rn = 11 + i
            assert len(by_round[rn]) == sz
        # Losers "round 5" in UI = round_num 15: exactly one consolidation match before l_final.
        assert len(by_round[15]) == 1


@pytest.mark.parametrize(
    "n,expected_w_len,expected_l_sizes",
    [
        (8, 3, [2, 2, 1, 1]),
        (9, 4, [3, 3, 2, 2, 1, 1]),
        (12, 4, [3, 3, 2, 2, 1, 1]),
        (33, 6, [9, 9, 5, 5, 3, 3, 2, 2, 1, 1]),
    ],
)
def test_double_elim_layer_shapes_spot_check(n, expected_w_len, expected_l_sizes):
    """Spot-check winners depth and full losers size vector for key player counts."""
    w_r1 = (n + 1) // 2
    w_layers = _winners_layer_sizes(w_r1)
    l_r1 = (w_r1 + 1) // 2
    l_sizes = _double_elim_loser_round_sizes(l_r1, w_layers)
    assert len(w_layers) == expected_w_len
    assert l_sizes == expected_l_sizes
    assert len(l_sizes) == 2 * len(w_layers) - 2


def test_wb_injection_layer_count_matches_winners_depth():
    """Each non-final WB dropout wave (W3..) maps to one parallel shelf in losers."""
    for n in range(8, 26):
        w_r1 = (n + 1) // 2
        w_layers = _winners_layer_sizes(w_r1)
        l_r1 = (w_r1 + 1) // 2
        l_sizes = _double_elim_loser_round_sizes(l_r1, w_layers)
        inj = _losers_wb_injection_dest_layers(l_sizes)
        nw = len(w_layers)
        if nw >= 4:
            assert len(inj) == nw - 3, f"n={n} inj={inj} nw={nw}"


@pytest.mark.asyncio
async def test_double_elim_w3_losers_land_on_parallel_shelf_not_merge_round():
    """12 players: W3 losers must hit losers round_num 14 (L4), not 13 (L3 merge)."""
    async with async_session_factory() as session:
        t = Tournament(guild_id=1, name="de-12-wb", format="1v1", mmr_playlist="solo_duel")
        session.add(t)
        await session.flush()
        n = 12
        seeded = [(i, False, False) for i in range(n)]
        bracket = await _create_double_elim_matches(session, t.id, seeded, False)
        assert bracket is not None
        r = await session.execute(
            select(BracketMatch).where(BracketMatch.bracket_id == bracket.id)
        )
        matches = {m.id: m for m in r.scalars().all()}
        w_r1 = (n + 1) // 2
        w_layers = _winners_layer_sizes(w_r1)
        l_sizes = _double_elim_loser_round_sizes((w_r1 + 1) // 2, w_layers)
        shelf0 = _losers_wb_injection_dest_layers(l_sizes)[0]
        target_rn = 11 + shelf0
        w_list = sorted(
            [m for m in matches.values() if m.bracket_section == "winners"],
            key=lambda m: (m.round_num, m.match_num),
        )
        w_final = w_list[-1]
        w_penult = [m for m in w_list if m.round_num == w_final.round_num - 1]
        assert len(w_penult) == 2
        for wm in w_penult:
            assert wm.loser_advances_to_match_id is not None
            lm = matches[wm.loser_advances_to_match_id]
            assert lm.bracket_section == "losers"
            assert lm.round_num == target_rn


@pytest.mark.parametrize("n", [8, 9, 12, 33])
def test_double_elim_losers_layer_count_formula(n):
    """Invariant: losers layer count is always 2 * winners layer count - 2 (n >= 8)."""
    w_r1 = (n + 1) // 2
    w_layers = _winners_layer_sizes(w_r1)
    l_r1 = (w_r1 + 1) // 2
    l_sizes = _double_elim_loser_round_sizes(l_r1, w_layers)
    assert len(l_sizes) == 2 * len(w_layers) - 2
    assert l_sizes[0] == l_sizes[1] == l_r1
    assert l_sizes[-1] == 1


@pytest.mark.parametrize("n", [8, 9, 12, 33])
def test_double_elim_preview_matches_generation_layer_counts(n):
    """Preview round keys 11.. match DB-style losers layer sizes for these n."""
    names = [f"P{i}" for i in range(n)]
    prev = preview_bracket_structure(names, "double_elim")
    w_r1 = (n + 1) // 2
    l_r1 = (w_r1 + 1) // 2
    w_layers = _winners_layer_sizes(w_r1)
    expected_layers = _double_elim_loser_round_sizes(l_r1, w_layers)
    assert prev["bracket_type"] == "double_elim"
    for lr, sz in enumerate(expected_layers, start=1):
        rkey = str(10 + lr)
        assert rkey in prev["rounds"]
        assert len(prev["rounds"][rkey]) == sz


@pytest.mark.asyncio
async def test_double_elim_preview_aligns_with_losers_tail():
    """Preview losers layer sizes match _double_elim_loser_round_sizes for sampled n."""
    for n in (8, 9, 11, 12, 16, 23, 33):
        names = [f"P{i}" for i in range(n)]
        prev = preview_bracket_structure(names, "double_elim")
        w_r1 = (n + 1) // 2
        l_r1 = (w_r1 + 1) // 2
        w_layers = _winners_layer_sizes(w_r1)
        expected_layers = _double_elim_loser_round_sizes(l_r1, w_layers)
        for lr, sz in enumerate(expected_layers, start=1):
            rkey = str(10 + lr)
            assert rkey in prev["rounds"]
            assert len(prev["rounds"][rkey]) == sz


@pytest.mark.asyncio
async def test_double_elim_l_final_winner_advances_to_grand_finals_slot2():
    """Losers bracket final winner must land on grand finals slot 2 (same request)."""
    async with async_session_factory() as session:
        t = Tournament(guild_id=1, name="de-gf-slot2", format="1v1", mmr_playlist="solo_duel")
        session.add(t)
        await session.flush()
        n = 8
        seeded = [(10_000 + i, False, False) for i in range(n)]
        bracket = await _create_double_elim_matches(session, t.id, seeded, False)
        assert bracket is not None
        r = await session.execute(
            select(BracketMatch).where(BracketMatch.bracket_id == bracket.id)
        )
        matches = list(r.scalars().all())
        losers = sorted(
            [m for m in matches if m.bracket_section == "losers"],
            key=lambda m: (m.round_num, m.match_num),
        )
        l_final = losers[-1]
        gf = next(m for m in matches if m.bracket_section == "grand_finals")
        assert l_final.parent_match_id == gf.id
        assert l_final.parent_match_slot == 2
        l_final.player1_id = 90_001
        l_final.player2_id = 90_002
        l_final.winner_player_id = 90_001
        await session.flush()
        await flush_double_elim_after_score_update(session, bracket.id, False)
        await session.refresh(gf)
        assert gf.player2_id == 90_001


@pytest.mark.asyncio
async def test_double_elim_l_final_gf_slot2_when_parent_link_missing():
    """Grand finals still receives losers champion if l_final.parent_match_id is broken."""
    async with async_session_factory() as session:
        t = Tournament(guild_id=1, name="de-gf-broken", format="1v1", mmr_playlist="solo_duel")
        session.add(t)
        await session.flush()
        n = 8
        seeded = [(11_000 + i, False, False) for i in range(n)]
        bracket = await _create_double_elim_matches(session, t.id, seeded, False)
        matches = list(
            (
                await session.execute(
                    select(BracketMatch).where(BracketMatch.bracket_id == bracket.id)
                )
            ).scalars().all()
        )
        losers = sorted(
            [m for m in matches if m.bracket_section == "losers"],
            key=lambda m: (m.round_num, m.match_num),
        )
        l_final = losers[-1]
        gf = next(m for m in matches if m.bracket_section == "grand_finals")
        l_final.parent_match_id = None
        l_final.parent_match_slot = None
        l_final.player1_id = 91_001
        l_final.player2_id = 91_002
        l_final.winner_player_id = 91_002
        await session.flush()
        await flush_double_elim_after_score_update(session, bracket.id, False)
        await session.refresh(gf)
        assert gf.player2_id == 91_002
