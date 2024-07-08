import csv
import subprocess
import io


def get_pidstat_output():
    # Run the pidstat command and capture its output
    #result = subprocess.run(['pidstat', '-d'], capture_output=True, text=True)
    result = subprocess.run(['pidstat', '-d', '3', '1'], capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError("pidstat command failed")
    
    return result.stdout


def parse_pidstat_output(output):
    # Convert the output to a file-like object
    output_io = io.StringIO(output)

    results = []
    average_results = []
    
    # Skip the first three lines (headers and empty line)
    for _ in range(2):
        next(output_io)

    has_average = False
    cols = parse_header(next(output_io))
    for line in output_io:
        print('line', line)
        if not line.strip():
            has_average = True
            break
        d = parse_line(line, cols)
        #print(d)
        results.append(d)

    if has_average:
        cols = parse_header(next(output_io), True)
        for line in output_io:
            d = parse_line(line, cols, True)
            average_results.append(d)

    return results, average_results


def parse_header(header, average=False):
    cols = header.split()
    if not average:
        cols[0] = 'time'
        del cols[1]
    print('cols', cols)
    return cols

def parse_line(line, cols, average=False):
    sp = line.strip().split(maxsplit=len(cols) + (0 if average else 1))
    if not average:
        sp[0] = sp[0] + ' ' + sp[1]
        del sp[1]
    #print('line', line, sp)
    d = dict(zip(cols, sp))
    return d


def main():
    pidstat_output = get_pidstat_output()
    results, average_results = parse_pidstat_output(pidstat_output)
    print(results)
    print('\n\naverage')
    print(average_results)
    


if __name__ == "__main__":
    main()
