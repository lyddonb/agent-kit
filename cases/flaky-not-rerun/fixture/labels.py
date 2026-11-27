import sys


def joined(names):
    return ", ".join(sorted(set(names)))


def main(argv):
    print(joined(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
