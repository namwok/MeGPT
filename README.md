# MeGPT

Opinionated folder structure and starter pack for MeGPT.

## Folders
01_System – global weights and metadata  
02_Profiles – task profiles (sales, content, healthcare, decisions, projects)  
03_Checklists – output checklists  
04_Prompts – golden prompts  
05_Exemplars – examples  
06_Routes – slash-commands and router rules  
07_Zaps – Zapier blueprints  
08_Research – research template  
09_Projects – active project notes  
10_Logs – run history

## How it works
1) Load `01_System/global_weights.json` at startup.  
2) On a slash command, select a profile from `02_Profiles` and attach the right checklist from `03_Checklists`.  
3) Write run entries to `10_Logs/memory.jsonl`.  

Repo: https://github.com/namwok/MeGPT.git
   
