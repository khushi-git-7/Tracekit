"""Fork-only probe for #722 (2): where one test_bounded part (200 sequences on one signer) spends its time, in-process."""
import cProfile, pstats, sys, time

sys.path.insert(0, "tests")
import test_bounded as tb  # noqa: E402

t0 = time.perf_counter()
pr = cProfile.Profile()
pr.enable()
wrong, reached = tb.ApprovalStateSpace.part(tb.RETRY, tb.RETRY_PREFIX, 0)
pr.disable()
print(f"one part: {time.perf_counter() - t0:.2f}s, wrong={len(wrong)}, reached={len(reached)}")
st = pstats.Stats(pr)
st.sort_stats("tottime").print_stats(25)
st.sort_stats("cumulative").print_stats(40)
