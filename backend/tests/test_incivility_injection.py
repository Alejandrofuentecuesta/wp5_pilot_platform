import random
from agents.STAGE.orchestrator import select_incivility_dimensions


def test_select_incivility_dimensions_probabilities():
    """Verify that select_incivility_dimensions has the correct probabilities over 10000 trials."""
    rng = random.Random(42)  # Seed for reproducibility
    
    trials = 10000
    impoliteness_count = 0
    hate_speech_count = 0
    democratic_threats_count = 0
    empty_runs = 0
    
    for _ in range(trials):
        selected = select_incivility_dimensions(rng)
        if not selected:
            empty_runs += 1
            
        if "impoliteness" in selected:
            impoliteness_count += 1
        if "hate_speech" in selected:
            hate_speech_count += 1
        if "democratic_threats" in selected:
            democratic_threats_count += 1
            
    # No empty runs should happen because of fallback
    assert empty_runs == 0
    
    # Expected probabilities including fallback:
    # impoliteness: ~84.3%
    # hate_speech: ~52.7%
    # democratic_threats: ~21.1%
    
    impoliteness_rate = impoliteness_count / trials
    hate_speech_rate = hate_speech_count / trials
    democratic_threats_rate = democratic_threats_count / trials
    
    assert 0.82 <= impoliteness_rate <= 0.87
    assert 0.50 <= hate_speech_rate <= 0.55
    assert 0.18 <= democratic_threats_rate <= 0.24

