import re
import sys

def main():
    req_path, free_path = sys.argv[1], sys.argv[2]

    freeze_versions = {}
    with open(free_path, 'r') as f:
        for i in f.readlines():
            line = i.strip()
            if not line:
                continue
            k, v = tuple(line.split('=='))
            freeze_versions[k.lower()] = v

    new_reqs = []
    with open(req_path, 'r') as f:
        for i in f.readlines():
            req = i.strip()
            if not req:
                continue
            if req.startswith('git+'):
                new_reqs.append(req)
                continue
            req = req.replace('_', '-')
            key = re.sub(r'\[\w+\]', '', req.lower(), 0)
            version = freeze_versions.get(key)
            if version:
                new_reqs.append(f'{req}=={version}')
            else:
                new_reqs.append(req)
    #print('requirements with versions pinned:')
    print('\n'.join(new_reqs))


if __name__ == '__main__':
    main()
