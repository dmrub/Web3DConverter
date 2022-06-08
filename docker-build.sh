#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

error() {
    echo >&2 "* Error: $@"
}

fatal() {
    error "$@"
    exit 1
}

message() {
    echo "$@"
}

update-git-repo() {
    # $1   - git repository url
    # $2   - source dir, where to clone
    # rest - additional arguments:
    #
    #        -n                     - don't chekout working dir        (git clone -n)
    #        --pull                 - pull instead of fetching         (git pull --rebase)
    #        --reset                - hard reset before pulling        (git reset --hard HEAD)
    #        --xrepo|--Xrepo <repo> - override the default repository
    #                                 with <repo>
    #        -b <branch>            - Point the local HEAD to <branch> (git clone -b <branch>
    #                                                                   git checkout <branch>)

    local git_url="${1:?}"
    local source_dir="${2:?}"
    shift 2

    local git_cmd=fetch
    local git_cmd_opt=
    local git_clone_opt=
    local git_branch=
    local git_reset=false
    while [ $# -gt 0 ]; do
        case "$1" in
            --pull)
                git_cmd=pull
                git_cmd_opt=--rebase
                ;;
            --reset)
                git_reset=true
                ;;
            -n)
                git_clone_opt="$git_clone_opt -n"
                ;;
            --xrepo|--Xrepo)
                shift
                if [ $# -gt 0 ]; then
                    if [ "${git_url}" ]; then
                        message "Overriding git URL \"${git_url:?}\" with \"${1:?}\""
                    fi
                    git_url="${1:?}"
                else
                    error "Missing argument (git URL) to --xrepo|--Xrepo option"
                    return 1
                fi
                ;;
            -b)
                shift
                if [ $# -gt 0 ]; then
                    if [ "${git_branch}" ]; then
                        message "Overriding git branch \"${git_branch:?}\" with \"${1:?}\""
                    fi
                    git_branch="${1:?}";
                    git_clone_opt="$git_clone_opt -b ${git_branch:?}"
                else
                    error "Missing argument (remote branch name) to -b option"
                    return 1
                fi
                ;;
            '')
                # Ignore empty argument
                shift;;
            *) eval $(devenv_die "updateGitRepo: Unrecognized argument: \"$1\"");
               ;;
        esac
        shift
    done

    local exit_code

    if [ "${git_branch}" ]; then
        message "Selecting ${git_branch:?} branch as HEAD"
    fi

    if [ -e "$source_dir" ]; then
        cd "$source_dir"

        if [ "$git_cmd" = "pull" -a "$git_reset" = "true" ]; then
            git reset --hard HEAD
        fi

        if [ "${git_branch}" ]; then
            git fetch && git checkout "${git_branch:?}"
            exit_code=$?
            if [ $exit_code -eq 0 ]; then
                if [ "$git_cmd" = "pull" ] && ! git symbolic-ref -q HEAD > /dev/null; then
                    # HEAD is detached, git pull will not work
                    # FIXME: Following is not really nice and should be improved
                    git fetch && git fetch --tags && git checkout "${git_branch:?}"
                else
                    git "$git_cmd" $git_cmd_opt
                fi
                exit_code=$?
            fi
        else
            git "$git_cmd" $git_cmd_opt
            exit_code=$?
        fi
        cd - &> /dev/null
        # simple error check for incomplete git clone
        if [ $exit_code -ne 0 -a ! -e "$source_dir/.git" ]; then
            error "'git $git_cmd $git_cmd_opt' failed !"
            error "Directory $source_dir exists but $source_dir/.git directory missing."
            error "Possibly 'git clone' command failed."
            error "You can try to remove $source_dir directory and try to update again."
        fi
    else
        message "Cloning $git_url to $source_dir..."
        test "${git_branch}" &&
            message "Selecting ${git_branch:?} branch as HEAD"
        git clone "$git_url" "$source_dir" $git_clone_opt
        exit_code=$?
    fi
    return $exit_code
}

# Define download function
define-download-func() {
    if type -f curl 2> /dev/null; then
        download() {
            local url=$1
            local dest=$2

            if [ ! -f "$dest" ]; then
                echo "Download $url"
                curl --location --output "$dest" "$url" || \
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
}

define-download-func

ASSIMP_URL=https://github.com/assimp/assimp
# ASSIMP_BRANCH=v3.3.1
ASSIMP_BRANCH=v5.2.4
LDRCONVERTER_URL=https://github.com/dmrub/LDRConverter
LDRCONVERTER_BRANCH=master
IMAGE_TAG=webldrconverter

if ! type -f git 2> /dev/null; then
    fatal "No git tool detected"
fi

usage() {
    echo "Build Web LDR Converter"
    echo
    echo "$0 [options]"
    echo "options:"
    echo "      --assimp-url=          Assimp Git URL"
    echo "                             (default: $ASSIMP_URL)"
    echo "      --ldrconverter-url=    LDR Converter Git URL"
    echo "                             (default: $LDRCONVERTER_URL)"
    echo "  -t, --tag=                 Image tag"
    echo "                             (default: $IMAGE_TAG)"
    echo "      --no-cache             Disable Docker cache"
    echo "      --help                 Display this help and exit"
}

while [[ $# > 0 ]]; do
    case "$1" in
        --assimp-url)
            ASSIMP_URL="$2"
            shift 2
            ;;
        --assimp-url=*)
            ASSIMP_URL="${1#*=}"
            shift
            ;;
        --ldrconverter-url)
            LDRCONVERTER_URL="$2"
            shift 2
            ;;
        --ldrconverter-url=*)
            LDRCONVERTER_URL="${1#*=}"
            shift
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --tag=*)
            IMAGE_TAG="${1#*=}"
            shift
            ;;
        --no-cache)
            NO_CACHE=--no-cache
            shift
            ;;
        --help)
            usage
            exit
            ;;
        --)
            shift
            break
            ;;
        -*)
            fatal "Unknown option $1"
            ;;
        *)
            break
            ;;
    esac
done

echo "LDR Converter Image Configuration:"
echo "ASSIMP_URL:        $ASSIMP_URL"
echo "LDRCONVERTER_URL:  $LDRCONVERTER_URL"
echo "IMAGE_TAG:         $IMAGE_TAG"
echo "NO_CACHE:          $NO_CACHE"

ASSIMP_DIR=$THIS_DIR/assimp
LDRCONVERTER_DIR=$THIS_DIR/LDRConverter

update-git-repo "$ASSIMP_URL" "$ASSIMP_DIR" \
                -b "$ASSIMP_BRANCH" \
                --reset --pull || \
    fatal "Could not update Assimp repository"

update-git-repo "$LDRCONVERTER_URL" "$LDRCONVERTER_DIR" \
                -b "$LDRCONVERTER_BRANCH" \
                --reset --pull || \
    fatal "Could not update LDRConverter repository"

docker build -t "$IMAGE_TAG" "$THIS_DIR"
