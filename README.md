Script to trim similar/duplicate fragments from video clips. While keeping audio in sync.

Note that it does not do what is often called "dropping frames" (i.e. removing them from container by replacing with PTS of a "similar enough" one from another part of the clip). It actually gets rid of them completely, making the resulting clip shorter in time.

Note also that some variables, such as mpdecimate thresholds or output codec settings, are currently hardcoded in the script. Mostly due to laziness ;-).

# Usage

Needs `Python3.7+` and `ffmpeg`.

```bash
$ mpdecimate_trim.py [--keep] [--skip SKIP] [--vaapi <render_device_filepath>] [--vaapi-decimate [render_device_filepath]] [--videotoolbox] [--videotoolbox-decimate] [--debug] <filepath>


This will take file at `<filepath>`, detect frames with certain similarity, re-encode it with them removed (using `libx265`/`hevc_vaapi`) and delete the original file.

The `--keep` switch makes it keep the original.

By default, re-encode happens even if no fragments to trim are found. This can be adjusted by setting `--skip` to minimum amount of remaining clip parts (e.g. `<=1` is equivalent to default, `2` means 1 trimmed fragment, and so on).

The `--vaapi` option enables [VA-API](https://trac.ffmpeg.org/wiki/Hardware/VAAPI) based hardware accelerated transcoding. Note that the script does not check whether supplied input and/or available GPU are capable of performing the transcode, if they are not the process will fail.

The `--vaapi-decimate` option enables VA-API based hardware accelerated decimate filter. If the optional device path is supplied, this device will be used. Otherwise, it will attempt to use device specified with `--vaapi` option. If neither device is specified, the script will fail. Note that on some older versions of `ffmpeg` this might fail even if VA-API transcoding works, not sure why. I have only tested this with `ffmpeg>=4.4.1`.

The `--videotoolbox` option enables Apple Video Toolbox based hardware accelerated transcoding. Note that this is super fast, but usually produces much bigger files than the CPU encoder. Only works on Apple Silicon machines and requires `ffmpeg>=4.4`.

The `--videotoolbox-decimate` option enables Apple Video Toolbox based hardware accelerated decimate filter. Note that it is often much slower than the CPU version, use only if extensive CPU use is undesirable. Only works on Apple Silicon machines and requires `ffmpeg>=4.4`.

The `--debug` flag prevents anything (both temporary and input) from getting removed, no matter if the script succeeded or not. Also enables debug loglevel for `ffmpeg` runs.

## The ffmpeg run turned interactive!

This can happen for example when the output file already exists. It may seems like the script is stuck, but really it is just waiting for user input.

Even though the _output_ is not visible, because it is redirected to a log file, you can still provide the _input_ as usual. So, to confirm overwriting existing file, just type `y<Enter>` like you normally would.

# vs_decimate?

Was a different experiment, using `vapoursynth`. Abandoned, because its' decimation algorithm does not fit my needs, and the whole process is also noticeably slower.

In case you want to use it for something, it needs `Python3.6+` and `vapoursynth` with `ffms2` and `damb`.
