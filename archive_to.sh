#!/bin/bash
# archive the target file/directory to destination directory,
# the name of archive is auto-generated.

src="$1"
dest="$2"

function usage() {
    echo "Usage: archive_to SRC DEST"
    echo "  SRC  source file"
    echo "  DEST destination directory"
}

if [ -z "$src" ]; then
    echo -e "Error: SRC is empty\n"
    usage
    exit 1
elif [ ! -e "$src" ]; then
    echo -e "Error: SRC does not exist\n"
    usage
    exit 1
elif [ -z "$dest" ]; then
    echo -e "Error: DEST is empty\n"
    usage
    exit 1
elif [ ! -d "$dest" ]; then
    echo -e "Error: DEST must be a directory\n"
    usage
    exit 1
fi

# extract name and extension
src_name=$(basename -- "$src")
src_dir=$(dirname -- "$src")
#src_ext="${src_name##*.}"
#src_name="${src_name%.*}"

# generate date tag
date_tag=$(date "+%Y%m%d%H%M%S")

# determine archive file name and path
if [ -d "$src" ]; then
    arc_ext=tgz
else
    arc_ext=zip
fi
arc_name="$src_name-${date_tag}.$arc_ext"
arc_path="$dest/$arc_name"
echo $arc_path

# do archive, methods: tgz
echo "Archiving $src to $arc_path"

export COPYFILE_DISABLE=1
pushd "$src_dir" > /dev/null
if [ -d "$src" ]; then
    tar czf "$arc_path" "$src_name"
else
    zip "$arc_path" "$src_name"
fi
popd > /dev/null
