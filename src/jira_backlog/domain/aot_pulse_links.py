"""Which spec-kit spec each AOT Pulse epic formalizes, and which later specs'
stories it takes on. Epics 1-9 are the nine user stories of 001-aot-bidhub;
epics 10-15 each have their own retroactive spec (013-018); the 002-012
list/detail enhancements are not in the epics document, so their stories join
the epic of the module they change."""

from jira_backlog.domain.backlog import EpicSpecLinks

AOT_PULSE_LINKS = {
    1: EpicSpecLinks(context=("001", 1)),
    2: EpicSpecLinks(context=("001", 9)),
    3: EpicSpecLinks(context=("001", 3), extra_stories=("005", "010")),
    4: EpicSpecLinks(context=("001", 2), extra_stories=("002", "006", "012")),
    5: EpicSpecLinks(context=("001", 4), extra_stories=("003", "011")),
    6: EpicSpecLinks(context=("001", 6), extra_stories=("004", "009")),
    7: EpicSpecLinks(context=("001", 5), extra_stories=("007", "008")),
    8: EpicSpecLinks(context=("001", 7)),
    9: EpicSpecLinks(context=("001", 8)),
    10: EpicSpecLinks(context=("013", None)),
    11: EpicSpecLinks(context=("014", None)),
    12: EpicSpecLinks(context=("015", None)),
    13: EpicSpecLinks(context=("016", None)),
    14: EpicSpecLinks(context=("017", None)),
    15: EpicSpecLinks(context=("018", None)),
}
