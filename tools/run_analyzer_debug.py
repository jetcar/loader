from analyzer import analyzer
import traceback

try:
    print('Calling load_draws()')
    draws = analyzer.load_draws()
    print('Loaded draws count:', len(draws))
    counters = analyzer.position_frequency(draws)
    print('Counters length:', len(counters))
    weights = analyzer.position_weights(counters, draws)
    print('Weights computed')
    num_freq = analyzer.overall_number_frequency(draws)
    print('Top num freq:', num_freq.most_common(5))
    candidates = analyzer.generate_candidate_pool(weights, num_freq, pool_size=100)
    print('Candidates generated:', len(candidates))
    suggestions = analyzer.build_suggestions(candidates)
    print('Suggestions top5:', suggestions['top5'])
    # write output file
    import json, os
    out = {
        'generated_at': 'debug',
        'game': 'Jokker',
        'suggestions': suggestions,
        'analysis': analyzer.build_analysis_report(draws, counters, weights, num_freq),
    }
    os.makedirs(analyzer.DATA_DIR, exist_ok=True)
    with open(analyzer.OUTPUT_FILE, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print('Wrote', analyzer.OUTPUT_FILE)
except Exception as e:
    print('EXCEPTION')
    traceback.print_exc()
