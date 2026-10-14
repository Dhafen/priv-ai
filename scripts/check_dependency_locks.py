"""Fail if resolution changed committed revisions or split the shared graph."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATIONS = {
    'engine': '.dependencies/swiftlet/Package.resolved',
    'app': 'localLLM.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved',
}
LOCKS = {'engine': 'swiftlet.Package.resolved', 'app': 'app.Package.resolved'}


def states(path):
    data = json.loads(path.read_text())
    return {pin['identity']: pin['state'] for pin in data['pins']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=DESTINATIONS)
    args = parser.parse_args()
    app = states(ROOT / 'dependencies' / LOCKS['app'])
    engine = states(ROOT / 'dependencies' / LOCKS['engine'])
    shared = app.keys() & engine.keys()
    split = sorted(name for name in shared if app[name] != engine[name])
    if split:
        raise SystemExit('Tests and app must share the same dependency revisions: ' + ', '.join(split))
    expected = app if args.phase == 'app' else engine
    actual = states(ROOT / DESTINATIONS[args.phase])
    if actual != expected:
        different = sorted(name for name in actual.keys() | expected.keys()
                           if actual.get(name) != expected.get(name))
        raise SystemExit('Resolved versions differ from the committed lock: ' + ', '.join(different))
    print(f'{args.phase}: {len(actual)} locked package revisions verified; {len(shared)} shared pins agree.')


if __name__ == '__main__':
    main()
