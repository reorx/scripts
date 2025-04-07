
extids=(
    "dhhpefjklgkmgeafimnjhojgjamoafof"
    "fmkadmapgofadopljbjfkapdkoienihi"
    "mpiodijhokgodhhofbcjdecpffjipkle"
    "knjbgabkeojmfdhindppcmhhfiembkeb"
    "gppongmhjkpfnbhagpmjfkannfbllamg"
)

ext_dir="$HOME/Library/Application Support/Google/Chrome/Default/Extensions"

function show_ext() {
    version_dir=$(ls -d "$ext_dir/$1/"* | head -n 1)
    echo "${1}:"
    grep '"name":' "$version_dir/manifest.json"
}

for i in "${extids[@]}"; do
    show_ext $i
done
