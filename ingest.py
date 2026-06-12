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

def load_mapping_table():
    map_file_input = os.path.join(BASE_DIR, 'input', 'Discipline maping.xlsx')
    map_file_root = os.path.join(BASE_DIR, 'Discipline maping.xlsx')
    map_file = map_file_input if os.path.exists(map_file_input) else map_file_root
    
    df_map = pd.read_excel(map_file)
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

def process_file_stream(file_stream, filename):
    db.init_db()
    mapping_dict = load_mapping_table()
    
    log.info("Ingesting %s from memory...", filename)
    df = pd.read_excel(file_stream)
    
    # Determine correct columns (handling slight variations)
    # The user explicitly wants _id and Availability ID to be distinct.
    avail_id_col = next((c for c in df.columns if 'availability id' in str(c).lower()), None)
    
    # Strictly look for _id. Since it's often exact, we can check for exactly '_id' or fall back to 'id' if needed, but strictly separate from availability id.
    int_id_col = next((c for c in df.columns if str(c).strip().lower() == '_id'), None)
    if not int_id_col:
        int_id_col = next((c for c in df.columns if str(c).strip().lower() == 'id'), None)
        
    fac_col = next((c for c in df.columns if 'facility' in str(c).lower() or 'setting' in str(c).lower()), None)
    disc_col = next((c for c in df.columns if 'discipline' in str(c).lower()), None)
    
    # Optional: Find an availability name or site name column
    name_col = next((c for c in df.columns if 'name' in str(c).lower() and 'discipline' not in str(c).lower()), None)
    
    if not all([avail_id_col, int_id_col, fac_col, disc_col]):
        log.warning("Skipping %s: Missing required columns.", filename)
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
            avail_name = str(row[name_col]).strip() if name_col else ""
            db.insert_or_ignore(avail_id, int_id, fac_type, disciplines_to_set, avail_name)
            added_count += 1
            
    log.info("Added %d records to database from %s.", added_count, filename)
    return True

def process_input_files():
    # Deprecated: Kept only if running locally on existing files
    db.init_db()
    
    # If someone still has an input folder, process them
    input_dir = os.path.join(BASE_DIR, 'input')
    if not os.path.exists(input_dir):
        return
        
    excel_files = glob.glob(os.path.join(input_dir, '*.xlsx'))
    excel_files = [f for f in excel_files if 'Discipline maping' not in os.path.basename(f)]

    for file_path in excel_files:
        with open(file_path, 'rb') as f:
            process_file_stream(f, os.path.basename(file_path))

if __name__ == "__main__":
    process_input_files()
