#!/usr/bin/env python3

import argparse
import logging
import os
import re
import sys
import time
from functools import partial
from os import path
from shutil import rmtree
from subprocess import run
from tempfile import mkdtemp


cargs = argparse.ArgumentParser(description="Trim video(+audio) clip, based on output from mpdecimate filter")
cargs.add_argument("--keep", action="store_true", help="Keep original file")
cargs.add_argument("--skip", type=int, help="Skip trimming, if less than SKIP parts found")
cargs.add_argument("--vaapi", type=str, help="Use VA-API device for hardware accelerated transcoding")
cargs.add_argument("--vaapi-decimate", nargs="?", const=True, help="Use VA-API device for hardware accelerated decimate filter")
cargs.add_argument("--videotoolbox", action="store_true", help="Use Apple Video Toolbox for hardware accelerated transcoding")
cargs.add_argument("--videotoolbox-decimate", action="store_true",help="Use Apple Video Toolbox for hardware accelerated decimate filter")
cargs.add_argument("--debug", action="store_true", help="Do not remove anything even on successful run. Use loglevel debug for all ffmpeg calls")
cargs.add_argument("--output-to-cwd", action="store_true", help="Save output file to where the script is run (default is location of the input file)")
cargs.add_argument("--vfparams", type=str, default="mpdecimate=lo=64*4:hi=64*10", help="mpdecimate vf parameters")
cargs.add_argument("filepath", help="File to trim")
cargs = cargs.parse_args()


logging.basicConfig(
    format="%(asctime)s[%(levelname).1s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG if cargs.debug else logging.INFO,
)


phase = "decimate"


def prof(s):
    e = time.time()
    logging.info(f"The {phase} phase took {time.strftime('%H:%M:%S', time.gmtime(e - s))}")
    return e

def profd(f):
    def a(*args, **kwargs):
        s = time.time()
        r = f(*args, **kwargs)
        prof(s)
        return r
    return a


tempdir = mkdtemp(prefix="mpdecimate_trim.")


_vaapi_args = ["-hwaccel", "vaapi", "-hwaccel_device"]

def hwargs_decimate():
    if cargs.videotoolbox_decimate:
        return ["-hwaccel", "videotoolbox"]

    if not cargs.vaapi_decimate:
        return []

    if cargs.vaapi_decimate is True:
        if not cargs.vaapi:
            raise Exception("--vaapi-decimate set to use --vaapi device, but --vaapi not set")

        return [*_vaapi_args, cargs.vaapi]

    return [*_vaapi_args, cargs.vaapi_decimate]

def hwargs_transcode():
    return [*_vaapi_args, cargs.vaapi, "-hwaccel_output_format", "vaapi"] if cargs.vaapi else []

@profd
def ffmpeg(co, *args):
    log_file_base = path.join(tempdir,  f"{phase}")
    log_file_out = f"{log_file_base}.stdout.log"
    log_file_err = f"{log_file_base}.stderr.log"

    args = ["ffmpeg", *args]

    args_for_log = " ".join(arg.replace(" ", "\\ ") for arg in args)
    logging.info(f"The {phase} phase is starting with command `{args_for_log}`")
    logging.info(f"Standard output capture: {log_file_out}")
    logging.info(f"Standard error capture: {log_file_err}")

    with open(log_file_out, "w", encoding="utf8") as out, open(log_file_err, "w", encoding="utf8") as err:
        result = run(args, stdout=out, stderr=err)
        out.flush()
        err.flush()
        if result.returncode == 0:
            if co:
                return log_file_err
            return

        logging.error(f"The {phase} phase failed with code {result.returncode}")
    logging.error("See above for where to look for details")
    sys.exit(3)


mpdecimate_fn = ffmpeg(
    True,
    *hwargs_decimate(),
    "-i", cargs.filepath,
    "-vf", cargs.vfparams,
    "-loglevel", "debug",
    "-f", "null", "-",
)


phase = "filter creation"


re_decimate = re.compile(
    r"^.*"
    r" (keep|drop)"
    r" pts:\d+"
    r" pts_time:(\d+(?:\.\d+)?)"
    r" drop_count:-?\d+"
    r"(?: keep_count:-?\d+)?$"
)
re_audio_in = re.compile(
    r"^(?:\[.*\])?\s*"
    r"Input stream #\d:\d"
    r" \(audio\):"
    r" \d+ packets read \(\d+ bytes\);"
    r" \d+ frames decoded"
    r"(?:; \d+ decode errors)?"
    r" \(\d+ samples\);"
    r"\s*$"
)
re_audio_out = re.compile(
    r"^(?:\[.*\])?\s*"
    r"Output stream #\d:\d"
    r" \(audio\):"
    r" \d+ frames encoded \(\d+ samples\);"
    r" \d+ packets muxed \(\d+ bytes\);"
    r"\s*$"
)

def get_frames_to_keep(mpdecimate_fn):
    to_keep = []
    dropping = True

    has_audio_in = False
    has_audio_out = False

    with open(mpdecimate_fn, encoding="utf8") as mpdecimate:
        for line in mpdecimate:
            values = re_decimate.findall(line)
            if not values:
                has_audio_in = has_audio_in or re_audio_in.fullmatch(line)
                has_audio_out = has_audio_out or re_audio_out.fullmatch(line)
                continue
            values = values[0]
            keep = values[0] == "keep"
            pts_time = values[1]

            if keep and dropping:
                to_keep.append([pts_time, None])
                dropping = False
            elif not keep and not dropping:
                to_keep[-1][1] = pts_time
                dropping = True

                if cargs.debug:
                    logging.debug(f"Keeping times {to_keep[-1][0]}-{to_keep[-1][1]}")

    return (to_keep, bool(has_audio_in and has_audio_out))


filter_fn = path.join(tempdir, "mpdecimate_filter")

@profd
def write_filter():
    logging.info(f"The {phase} phase is starting")
    logging.info(f"Filter definition: {filter_fn}")

    frames_to_keep, has_audio = get_frames_to_keep(mpdecimate_fn)
    if cargs.debug:
        logging.debug(f"Has audio: {has_audio}")
    if cargs.skip and len(frames_to_keep) < cargs.skip:
        logging.warn(f"Less than {cargs.skip} parts detected, avoiding re-encode")
        sys.exit(2)

    with open(filter_fn, "w", encoding="utf8") as fg:
        fg.write("ffconcat version 1.0\n")
        for i, (s, e) in enumerate(frames_to_keep):
            # NOTE ffconcat takes paths relative to its location, *not* cwd.
            # Need to supply absolute path for it to find the input file.
            fg.write(f"\nfile '{path.abspath(cargs.filepath)}'\n")
            fg.write(f"inpoint {s}\n")
            if e is not None:
                fg.write(f"outpoint {e}\n")
        fg.flush()

write_filter()


phase = "transcode"


def get_enc_args():
    if cargs.videotoolbox:
        return ["hevc_videotoolbox", "-q:v", "65"]
    if cargs.vaapi:
        return ["hevc_vaapi", "-qp", "24"]
    return ["libx265", "-preset", "fast", "-crf", "30"]

fout, ext = path.splitext(cargs.filepath)
if cargs.output_to_cwd:
    fout = path.basename(fout)
ffmpeg(
    False,
    *(["-loglevel", "debug"] if cargs.debug else []),
    *hwargs_transcode(),
    "-safe", "0", "-segment_time_metadata", "1",
    "-i", filter_fn,
    "-af", "aselect=concatdec_select",
    # XXX The part below doesn't seem necessary, but leaving it here just in case.
    # "-vf", "select=concatdec_select",
    "-c:v", *get_enc_args(),
    f"{fout}.trimmed{ext}",
)


if cargs.debug:
    logging.debug("Debug enabled, not removing anything")
    sys.exit(0)

if not cargs.keep:
    logging.info(f"Removing the original file at {cargs.filepath}")
    os.remove(cargs.filepath)

rmtree(tempdir)
