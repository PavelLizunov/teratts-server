"""Focused model-free checks requested for the isolated ASR implementation."""
import math
import unittest

from decoder import ContextBias, Hypothesis, finite_topk, merge_and_prune


class DecoderChecks(unittest.TestCase):
    def test_forbidden_or_nonfinite_ids_cannot_fill_large_beam(self):
        self.assertEqual(finite_topk([100, -math.inf, 2, math.nan, 3], [1, 2, 3, 4], 10), [4, 2])

    def test_completed_numerical_phrase_and_prefix_refund(self):
        graph = ContextBias([[513, 519, 533]], 1.5)
        state, total = (), 0.0
        for token in [513, 519, 533]:
            delta, state = graph.step(state, token)
            total += delta
        self.assertEqual(total + graph.finalize(state), 4.5)
        state, total = (), 0.0
        for token in [513, 519, 700]:
            delta, state = graph.step(state, token)
            total += delta
        self.assertEqual(total + graph.finalize(state), 0.0)
        delta, state = graph.step((), 513)
        self.assertEqual(delta + graph.finalize(state), 0.0)

    def test_empty_graph_optout_has_no_hint_credit(self):
        graph = ContextBias([], 100)
        self.assertEqual(graph.step((), 513), (0.0, ()))
        self.assertEqual(graph.finalize(()), 0)

    def test_matching_string_from_wrong_language_does_not_trigger(self):
        graph = ContextBias([[513, 519]], 1.5)
        self.assertEqual(graph.step((), 260), (0.0, ()))

    def test_overlapping_phrases_and_duplicate_paths(self):
        graph = ContextBias([[1, 2], [1, 2], [2, 3]], 1)
        total, state = 0, ()
        for token in [1, 2, 3]:
            delta, state = graph.step(state, token)
            total += delta
        # Shared token 2 is covered once, not once per overlapping phrase.
        self.assertEqual(total + graph.finalize(state), 3)

    def test_duplicate_acoustic_alignments_logadd(self):
        h = Hypothesis((513,), (2,), (-1,), -2, 3, 0, (), None)
        result = merge_and_prune([h, h], 4)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].score, -2 + math.log(2))


if __name__ == '__main__':
    unittest.main()
