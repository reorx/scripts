# ----------------------------------
# Colors
# ----------------------------------
NOCOLOR='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
ORANGE='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
LIGHTGRAY='\033[0;37m'
DARKGRAY='\033[1;30m'
LIGHTRED='\033[1;31m'
LIGHTGREEN='\033[1;32m'
YELLOW='\033[1;33m'
LIGHTBLUE='\033[1;34m'
LIGHTPURPLE='\033[1;35m'
LIGHTCYAN='\033[1;36m'
WHITE='\033[1;37m'

echo -e "You take the ${BLUE}blue pill${NOCOLOR}—the story ends, you wake up in bed and believe whatever you want to believe. You take the ${RED}red pill${NOCOLOR}—you stay in Wonderland, and I show you how deep the rabbit hole goes. Remember: all I’m offering is the ${YELLOW}truth${NOCOLOR}. Nothing more."

function paint() {
    echo -e "${!1}${2}${NOCOLOR}"
}

paint RED wtf
