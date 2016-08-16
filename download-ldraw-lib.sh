#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

error() {
    echo >&2 "* Error: $@"
}

fatal() {
    error "$@"
    exit 1
}

if type -f curl 2> /dev/null; then
    download() {
	local url=$1
	local dest=$2

	if [ ! -f "$dest" ]; then
            echo "Download $url"
            curl --output "$dest" "$url" || \
		fatal "Could not load $url to $dest"
	else
	    echo "File $dest exists, skipping download"
	fi
    }
elif type -f wget 2> /dev/null; then
    download() {
	local url=$1
	local dest=$2

	if [ ! -f "$dest" ]; then
            echo "Download $url"
            wget -O "$dest" "$url" || \
                fatal "Could not load $url to $dest"
	else
	    echo "File $dest exists, skipping download"
	fi
    }
else
    fatal "No download tool detected (checked: curl, wget)"
fi

UNF_PARTS_URL=http://www.ldraw.org/library/unofficial/ldrawunf.zip
UNF_PARTS_ZIP=ldrawunf.zip
COMPLETE_PARTS_URL=http://www.ldraw.org/library/updates/complete.zip
COMPLETE_PARTS_ZIP=complete.zip

download "$COMPLETE_PARTS_URL" "$COMPLETE_PARTS_ZIP"
download "$UNF_PARTS_URL" "$UNF_PARTS_ZIP"

unzip -o "$COMPLETE_PARTS_ZIP" || exit 1
mkdir -p ldraw/Unofficial || exit 1
unzip -o -d ldraw/Unofficial "$UNF_PARTS_ZIP" || exit 1

rm "$COMPLETE_PARTS_ZIP" "$UNF_PARTS_ZIP"
