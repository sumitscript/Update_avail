import os
import glob
import pandas as pd
import shutil
import db

from logging_config import get_logger

log = get_logger(__name__)

DISCIPLINE_MAPPING = {
    'physical therapy': 'PT',
    'physical therapist assistant': 'PTA',
    'occupational therapy': 'OT',
    'occupational therapist assistant': 'OTA',
    'speech-language pathology': 'SLP'
}

# Resolve paths relative to this script so they work regardless of the
# process working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, 'input')
ARCHIVE_DIR = os.path.join(BASE_DIR, 'archive')
# The mapping workbook lives alongside the input files.
MAP_FILE = os.path.join(INPUT_DIR, 'Discipline maping.xlsx')

def load_mapping_table():
    df_map = pd.read_excel(MAP_FILE)
    mapping_dict = {}
    for index, row in df_map.iterrows():
        disc = str(row['Discipline']).strip().upper()
        fac = str(row['Facility Type']).strip().upper()
        # Key: (Discipline Acronym, Facility Type)
        # Value: list of specializations
        key = (disc, fac)
        if key not in mapping_dict:
            mapping_dict[key] = []
        mapping_dict[key].append({
            'disciplineName': disc,
            'disciplineId': str(row['Discipline Id']),
            'specializationName': str(row['Specialization']),
            'specializationId': str(row['speclization Id'])
        })
    return mapping_dict

def process_file(file_path):
    db.init_db()
    mapping_dict = load_mapping_table()
    
    log.info("Ingesting %s...", file_path)
    df = pd.read_excel(file_path)
    
    # Determine correct columns (handling slight variations)
    avail_id_col = next((c for c in df.columns if 'availability id' in c.lower()), None)
    int_id_col = next((c for c in df.columns if '_id' in c.lower()), None)
    fac_col = next((c for c in df.columns if 'facility' in c.lower() or 'setting' in c.lower()), None)
    disc_col = next((c for c in df.columns if 'discipline' in c.lower()), None)
    
    if not all([avail_id_col, int_id_col, fac_col, disc_col]):
        log.warning("Skipping %s: Missing required columns.", file_path)
        return False
        
    added_count = 0
    for index, row in df.iterrows():
        avail_id = row[avail_id_col]
        int_id = row[int_id_col]
        fac_type = str(row[fac_col]).strip().upper()
        raw_disciplines = str(row[disc_col])
        
        if pd.isna(raw_disciplines) or raw_disciplines.lower() == 'nan':
            continue
            
        disciplines_to_set = []
        
        # Split and map
        for d in raw_disciplines.split(','):
            d_clean = d.strip().lower()
            acronym = DISCIPLINE_MAPPING.get(d_clean)
            if not acronym:
                continue
                
            # Look up specializations for this acronym and facility type
            specs = mapping_dict.get((acronym, fac_type), [])
            disciplines_to_set.extend(specs)
            
        if disciplines_to_set:
            db.insert_or_ignore(avail_id, int_id, fac_type, disciplines_to_set)
            added_count += 1
            
    log.info("Added %d records to database from %s.", added_count, file_path)

    # Move to archive (ensure the destination exists).
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    filename = os.path.basename(file_path)
    shutil.move(file_path, os.path.join(ARCHIVE_DIR, filename))
    return True

def process_input_files():
    db.init_db()

    excel_files = glob.glob(os.path.join(INPUT_DIR, '*.xlsx'))
    # Don't try to ingest the mapping workbook itself.
    map_name = os.path.basename(MAP_FILE)
    excel_files = [f for f in excel_files if os.path.basename(f) != map_name]

    if not excel_files:
        log.info("No availability files to ingest in %s.", INPUT_DIR)

    for file_path in excel_files:
        process_file(file_path)

if __name__ == "__main__":
    process_input_files()
