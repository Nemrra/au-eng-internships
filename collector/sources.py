"""Aggregator / special sources that aren't tied to one registry employer."""

AGGREGATORS = [
    {"name": "Prosple / GradAustralia", "spec": {"type": "prosple"}, "default_au": True},
    {"name": "GradConnection (SEEK Grad)", "spec": {"type": "gradconnection"}, "default_au": True},
    {"name": "Talent.com AU", "spec": {"type": "talent"}, "default_au": True},
    {"name": "Blackbird portfolio jobs", "spec": {"type": "getro_board", "base": "https://jobs.blackbird.vc"}},
    {"name": "AirTree portfolio jobs", "spec": {"type": "getro_board", "base": "https://jobs.airtree.vc"}},
    {"name": "Square Peg portfolio jobs", "spec": {"type": "getro_board", "base": "https://squarepeg.getro.com"}},
    {"name": "Folklore portfolio jobs", "spec": {"type": "getro_board", "base": "https://roles.folklore.vc"}},
    {"name": "Techstars portfolio jobs", "spec": {"type": "getro_board", "base": "https://jobs.techstars.com"}},
    {"name": "Simplify Summer 2027 internships (GitHub)", "spec": {"type": "simplify",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"}},
    {"name": "Simplify New Grad (GitHub)", "spec": {"type": "simplify",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"}},
    {"name": "speedyapply 2027 college jobs (GitHub)", "spec": {"type": "readme_list",
        "url": "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/HEAD/README.md"}},
    {"name": "jobright 2026 engineer internships (GitHub)", "spec": {"type": "readme_list",
        "url": "https://raw.githubusercontent.com/jobright-ai/2026-Engineer-Internship/HEAD/README.md"}},
    {"name": "Amazon jobs AU", "spec": {"type": "amazon"}, "company": "Amazon", "default_au": True},
    {"name": "Atlassian careers", "spec": {"type": "atlassian"}, "company": "Atlassian"},
    {"name": "Apple jobs AU internships", "spec": {"type": "apple"}, "company": "Apple", "default_au": True},
    {"name": "Google careers AU interns", "spec": {"type": "google"}, "company": "Google", "default_au": True},
    {"name": "Canva (SmartRecruiters)", "spec": {"type": "smartrecruiters", "company": "Canva"}, "company": "Canva"},
]

# Sources deliberately NOT fetched by the collector (blocked or disallowed for bots).
# The scheduled Claude sweep covers these through web search instead.
SWEEP_ONLY = ["LinkedIn", "SEEK", "Indeed", "Jora", "Glassdoor", "APSJobs", "Wellfound", "Workforce Australia",
              "careers.vic.gov.au", "iworkfor.nsw.gov.au", "University careers portals (login)"]
