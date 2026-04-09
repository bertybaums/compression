"""Tests for the UGF tokenizer."""

import pytest
from tokenizer.ugf_tokenizer import UGFTokenizer


@pytest.fixture
def tok():
    return UGFTokenizer()


class TestBasicEncoding:
    def test_simple_sentence(self, tok):
        text = "the water is good"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        assert decoded == text

    def test_with_special_tokens(self, tok):
        text = "the water is good"
        ids = tok.encode(text, add_special_tokens=True)
        assert ids[0] == tok.bos_token_id
        assert ids[-1] == tok.eos_token_id

    def test_punctuation(self, tok):
        text = "is it good? yes, it is!"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        assert decoded == text

    def test_numerals(self, tok):
        text = "there are 3 things"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        assert decoded == text

    def test_capitalization_roundtrip(self, tok):
        text = "The water is Good"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        assert decoded == "The water is Good"

    def test_contractions(self, tok):
        text = "don't you think it's wrong"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        # "it's" is not in the vocab (only "he's", "who's" etc.), so it maps to UNK
        # but "don't" should survive
        assert "don't" in decoded


class TestValidation:
    def test_valid_text(self, tok):
        is_valid, violations = tok.validate("the water is good")
        assert is_valid
        assert violations == []

    def test_invalid_text(self, tok):
        is_valid, violations = tok.validate("the dilemma is problematic")
        assert not is_valid
        assert "dilemma" in violations
        assert "problematic" in violations

    def test_mixed_text(self, tok):
        is_valid, violations = tok.validate("the equilibrium is not good")
        assert not is_valid
        assert "equilibrium" in violations
        assert len(violations) == 1

    def test_compliance_ratio(self, tok):
        ratio = tok.ugf_compliance_ratio("the good bad wrong water")
        assert ratio == 1.0

        ratio = tok.ugf_compliance_ratio("the dilemma is problematic")
        # 2 out of 4 words are violations
        assert ratio == pytest.approx(0.5)

    def test_capitalized_words_are_valid(self, tok):
        is_valid, violations = tok.validate("The Water Is Good")
        assert is_valid

    def test_punctuation_is_valid(self, tok):
        is_valid, violations = tok.validate("is it good? yes!")
        assert is_valid


class TestVocabSize:
    def test_vocab_size_reasonable(self, tok):
        assert 3500 < tok.vocab_size < 4000

    def test_special_tokens_present(self, tok):
        vocab = tok.get_vocab()
        for special in ["<PAD>", "<UNK>", "<BOS>", "<EOS>", "<CAP>"]:
            assert special in vocab

    def test_pad_token_is_zero(self, tok):
        assert tok.pad_token_id == 0


class TestEdgeCases:
    def test_empty_string(self, tok):
        ids = tok.encode("", add_special_tokens=False)
        assert ids == []

    def test_unknown_word_maps_to_unk(self, tok):
        ids = tok.encode("philosophy", add_special_tokens=False)
        assert ids == [tok.unk_token_id]

    def test_newline_handling(self, tok):
        text = "the first thing\nthe second thing"
        ids = tok.encode(text, add_special_tokens=False)
        decoded = tok.decode(ids)
        assert "\n" in decoded
