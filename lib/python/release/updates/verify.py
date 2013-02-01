from copy import copy
import os
import re
from util.algorithms import getChunk


class UpdateVerifyError(Exception):
    pass


class UpdateVerifyConfig(object):
    comment_regex = re.compile("^#")
    key_write_order = ("release", "product", "platform", "build_id", "locales",
                       "channel", "patch_types", "from", "aus_server",
                       "ftp_server_from", "ftp_server_to", "to")
    global_keys = ("product", "platform", "channel", "aus_server", "to")
    release_keys = ("release", "build_id", "locales", "patch_types", "from",
                    "ftp_server_from", "ftp_server_to")
    first_only_keys = ("from", "aus_server", "to")
    compare_attrs = global_keys + ("releases",)

    def __init__(self, product=None, platform=None, channel=None,
                 aus_server=None, to=None):
        self.product = product
        self.platform = platform
        self.channel = channel
        self.aus_server = aus_server
        self.to = to
        self.releases = []

    def __eq__(self, other):
        self_list = [getattr(self, attr) for attr in self.compare_attrs]
        other_list = [getattr(other, attr) for attr in self.compare_attrs]
        return self_list == other_list

    def __ne__(self, other):
        return not self.__eq__(other)

    def _parseLine(self, line):
        entry = {}
        items = re.findall("\w+=[\"'][^\"']*[\"']", line)
        for i in items:
            m = re.search(
                "(?P<key>\w+)=[\"'](?P<value>.+)[\"']", i).groupdict()
            if m["key"] not in self.global_keys and m["key"] not in self.release_keys:
                raise UpdateVerifyError(
                    "Unknown key '%s' found on line:\n%s" % (m["key"], line))
            if m["key"] in entry:
                raise UpdateVerifyError("Multiple values found for key '%s' on line:\n%s" % (m["key"], line))
            entry[m["key"]] = m["value"]
        if not entry:
            raise UpdateVerifyError("No parseable data in line '%s'" % line)
        return entry

    def _addEntry(self, entry, first):
        releaseKeys = {}
        for k, v in entry.items():
            if k in self.global_keys:
                setattr(self, k, entry[k])
            elif k in self.release_keys:
                # "from" is reserved in Python
                if k == "from":
                    releaseKeys["from_path"] = v
                else:
                    releaseKeys[k] = v
        self.addRelease(**releaseKeys)

    def read(self, config):
        f = open(config)
        # Only the first non-comment line of an update verify config should
        # have a "from" and"ausServer". Ignore any subsequent lines with them.
        first = True
        for line in f.readlines():
            # Skip comment lines
            if self.comment_regex.search(line):
                continue
            self._addEntry(self._parseLine(line), first)
            first = False

    def write(self, fh):
        first = True
        for releaseInfo in self.releases:
            for key in self.key_write_order:
                if key in self.global_keys and (first or key not in self.first_only_keys):
                    value = getattr(self, key)
                elif key in self.release_keys:
                    value = releaseInfo[key]
                else:
                    value = None
                if value is not None:
                    fh.write(key)
                    fh.write("=")
                    if isinstance(value, (list, tuple)):
                        fh.write('"%s" ' % " ".join(value))
                    else:
                        fh.write('"%s" ' % str(value))
            # Rewind one character to avoid having a trailing space
            fh.seek(-1, os.SEEK_CUR)
            fh.write("\n")
            first = False

    def addRelease(self, release=None, build_id=None, locales=[],
                   patch_types=['complete'], from_path=None,
                   ftp_server_from=None, ftp_server_to=None):
        """Locales and patch_types can be passed as either a string or a list.
           If a string is passed, they will be converted to a list for internal
           storage"""
        if self.getRelease(build_id, from_path):
            raise UpdateVerifyError("Couldn't add release identified by build_id '%s' and from_path '%s': already exists in config" % (build_id, from_path))
        if isinstance(locales, basestring):
            locales = sorted(list(locales.split()))
        if isinstance(patch_types, basestring):
            patch_types = list(patch_types.split())
        self.releases.append({
            "release": release,
            "build_id": build_id,
            "locales": locales,
            "patch_types": patch_types,
            "from": from_path,
            "ftp_server_from": ftp_server_from,
            "ftp_server_to": ftp_server_to,
        })

    def addLocaleToRelease(self, build_id, locale, from_path=None):
        r = self.getRelease(build_id, from_path)
        if not r:
            raise UpdateVerifyError("Couldn't add '%s' to release identified by build_id '%s' and from_path '%s': '%s' doesn't exist in this config." % (locale, build_id, from_path, build_id))
        r["locales"].append(locale)
        r["locales"] = sorted(r["locales"])

    def getRelease(self, build_id, from_path):
        for r in self.releases:
            if r["build_id"] == build_id and r["from"] == from_path:
                return r
        return {}

    def getFullReleaseTests(self):
        return [r for r in self.releases if r["from"] is not None]

    def getQuickReleaseTests(self):
        return [r for r in self.releases if r["from"] is None]

    def getChunk(self, chunks, thisChunk):
        fullTests = []
        quickTests = []
        for test in self.getFullReleaseTests():
            for locale in test["locales"]:
                fullTests.append([test["build_id"], locale, test["from"]])
        for test in self.getQuickReleaseTests():
            for locale in test["locales"]:
                quickTests.append([test["build_id"], locale, test["from"]])
        allTests = getChunk(fullTests, chunks, thisChunk)
        allTests.extend(getChunk(quickTests, chunks, thisChunk))

        newConfig = UpdateVerifyConfig(self.product, self.platform,
                                       self.channel, self.aus_server,
                                       self.to)
        for t in allTests:
            build_id, locale, from_path = t
            if from_path == "None":
                from_path = None
            r = self.getRelease(build_id, from_path)
            try:
                newConfig.addRelease(r["release"], build_id, locales=[],
                                     ftp_server_from=r["ftp_server_from"],
                                     ftp_server_to=r["ftp_server_to"],
                                     patch_types=r["patch_types"], from_path=from_path)
            except UpdateVerifyError:
                pass
            newConfig.addLocaleToRelease(build_id, locale, from_path)
        return newConfig
