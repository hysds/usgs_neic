#!/bin/bash

set -e

#check input args
if [ -z "$1" ] 
then
    echo "No minimum magnitude specified"
    exit 1
fi
if [ -z "$2" ] 
then
    echo "No updated_since time specified"
    exit 1
fi
if [ -z "$3" ] 
then
    echo "No geojson product specified"
    exit 1
fi

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
${DIR}/query_neic.py --minmag "${1}" --updatedafter "${2}" --polygon "${3}" --submit
