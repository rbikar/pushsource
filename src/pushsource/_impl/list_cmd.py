"""List all push items found in one or more sources.

configuration:

  A simple configuration file may be provided at /etc/pushsource.conf and
  ~/.config/pushsource.conf in order to set up backends bound to a
  particular environment, as in example:

    # in ~/.config/pushsource.conf
    sources:
      # this will add a 'fedkoji' source, making it possible to do:
      # pushsource-ls fedkoji:rpm=python3-3.7.5-2.fc31.x86_64.rpm
      - name: fedkoji
        url: 'koji:https://koji.fedoraproject.org/kojihub'

see also:

  Information on available backends can be found at:
  https://release-engineering.github.io/pushsource/userguide.html

"""

import logging
import os
from argparse import ArgumentParser, RawDescriptionHelpFormatter
import subprocess
import sys
import enum

import attr
import yaml
from frozendict.core import frozendict

import pushsource
from pushsource import Source

LOG = logging.getLogger("pushsource-ls")

EXCLUDED_ATTRIBUTES = [
    "opener",
]


class ItemDumper(yaml.SafeDumper):
    # Custom dumper adding support for any types appearing on pushitems
    # which are not natively supported by pyyaml.

    @classmethod
    def represent_enum(cls, dumper: yaml.Dumper, value: enum.Enum):
        # enums are unwrapped and represented using whatever's the underlying
        # type, e.g. a string enum of value "foo" will be serialized the
        # same as a plain string "foo".
        return dumper.represent_data(value.value)

    @classmethod
    def add_enum_representers(cls):
        # Register our enum representer for any enum classes in the API.
        for attrname in dir(pushsource):
            attrval = getattr(pushsource, attrname)
            if isinstance(attrval, enum.EnumMeta):
                cls.add_representer(attrval, cls.represent_enum)


ItemDumper.add_enum_representers()
ItemDumper.add_representer(frozendict, ItemDumper.represent_dict)


def format_python(item):
    return repr(item) + ","


def format_python_black(item):
    code = format_python(item)
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        ["black", "-c", code], universal_newlines=True, stdout=subprocess.PIPE
    )
    (out, _) = proc.communicate()
    if proc.returncode:
        raise RuntimeError("Cannot format with black, exit code %s" % proc.returncode)
    return out


def format_yaml(item):
    data = {
        type(item).__name__: attr.asdict(
            item,
            recurse=True,
            filter=lambda attribute, _: attribute.name not in EXCLUDED_ATTRIBUTES,
        )
    }
    return yaml.dump([data], Dumper=ItemDumper)


def default_format():
    # Pick the best available formatter.
    try:
        format_python_black("dummy")
        return "python-black"
    except:  # pylint: disable=bare-except
        return "python"


FORMATTERS = {
    "python": format_python,
    "python-black": format_python_black,
    "yaml": format_yaml,
}


def load_conf(filename):
    with open(filename, "rt") as f:
        conf = yaml.safe_load(f)

    try:
        for source in conf.get("sources") or []:
            name = source["name"]
            url = source["url"]
            Source.register_backend(name, Source.get_partial(url))
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Error loading config from %s", filename)
        sys.exit(52)


def load_all_conf():
    for filename in [
        "/etc/pushsource.conf",
        os.path.expanduser("~/.config/pushsource.conf"),
    ]:
        if os.path.exists(filename):
            load_conf(filename)


def run(args):
    load_all_conf()

    for url in args.src_url:
        with Source.get(url) as source:
            sys.stdout.write("# Loaded source %s\n" % url)

            formatter = FORMATTERS.get(args.format)

            itemcount = 0

            for pushitem in source:
                out = formatter(pushitem)
                sys.stdout.write("%s\n" % out)
                sys.stdout.flush()
                itemcount += 1

            sys.stdout.write("# %s item(s) found in source\n" % itemcount)


def main():
    LOG.setLevel(logging.INFO)

    parser = ArgumentParser(
        description=__doc__, formatter_class=RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--format",
        default=default_format(),
        choices=["python", "python-black", "yaml"],
        help="Output format",
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "src_url", nargs="+", help="Push source URL(s) (example: staged:/some/dir)"
    )

    p = parser.parse_args()

    if p.debug:
        logging.basicConfig(format="%(threadName)s %(message)s")
        LOG.setLevel(logging.DEBUG)
        logging.getLogger("pushsource").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(format="%(message)s")

    run(p)
