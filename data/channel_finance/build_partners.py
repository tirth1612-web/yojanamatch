"""
Builds channel_partners.json from the 8 official NSFDC partner lists.
Each partner is tagged with:
  - type: SCA / PSB / RRB / NBFC-MFI / Small Finance Bank / Cooperative Society / Other Agency
  - loan_categories: which of the 3 NSFDC credit products they're assumed to route
    (micro_finance <= 1.4L, term_loan <= 50L, education_loan)
  - eligibility_status: SIMULATED demo field (real NPA/fund-utilization data is
    NSFDC-internal and not publicly available - see note printed at the end)

ASSUMPTION (not official NSFDC policy - stated for hackathon demo transparency):
  - SCA: primary state-designated channel -> all 3 categories
  - PSB / RRB / Small Finance Bank: larger balance sheets -> term_loan + education_loan
    (can also do micro_finance, so included there too)
  - NBFC-MFI / Cooperative Society (mostly women-focused): specialise in small-ticket
    lending -> micro_finance only
  - Other Agencies: sector-specific (SIDBI = industrial term loans, JHARCRAFT =
    artisan micro-finance, NEDFi = all categories for NE region) -> handled individually
"""
import json
import random

random.seed(42)  # reproducible demo data

partners = []
pid = 1

def add(name, ptype, state, address, categories):
    global pid
    partners.append({
        "partner_id": f"CP-{pid:03d}",
        "name": name,
        "type": ptype,
        "state": state,
        "address": address,
        "loan_categories": categories,
        # SIMULATED - see module docstring. ~80% active, ~20% flagged, for demo only.
        "eligibility_status": "active" if random.random() > 0.2 else "high_npa_flagged",
        "latitude": None,   # filled in by geocode_partners.py (needs internet)
        "longitude": None
    })
    pid += 1

SCA = ["micro_finance", "term_loan", "education_loan"]
BANK = ["term_loan", "education_loan", "micro_finance"]
MFI = ["micro_finance"]

# --- 1. State Channelising Agencies (38) ---
sca_data = [
    ("Andhra Pradesh Scheduled Castes Cooperative Finance Corporation Ltd", "Andhra Pradesh", "SP River View Apartment, 3rd Floor, Tadepalli, Amaravati - 522501"),
    ("Andhra Pradesh State Financial Corporation (APSFC)", "Andhra Pradesh", "APSFC Bhavan, Plot OS No.2, 2nd Cross, 3rd Road, Industrial Park, Vijayawada - 520007"),
    ("Assam State Scheduled Castes Development Corporation Ltd", "Assam", "Swahid Dilip Hazarika Path, Sarumotoria, Guwahati - 781006"),
    ("Bihar State Scheduled Castes Cooperative Development Corporation Ltd", "Bihar", "RN-212, Officers Colony (S-A), Bailey Road, Patna - 800001"),
    ("Chandigarh SC & OBC Development Corporation Ltd", "Chandigarh", "3rd Floor, Additional Town Hall Building, Sector-17-D, Chandigarh - 160017"),
    ("Chhattisgarh State Antyavasayi Cooperative Finance & Development Corporation (CGSCFDC)", "Chhattisgarh", "4th Floor, Chhattisgarh Housing Board Bhavan, Naya Raipur, Chhattisgarh - 492101"),
    ("Delhi SC/ST/OBC/Minorities Finance & Development Corporation", "Delhi", "Ambedkar Bhavan, Sector-16, Rohini, Delhi - 110085"),
    ("Gujarat Scheduled Castes Development Corporation", "Gujarat", "Dr. Jivraj Mehta Bhavan, Block-10, 2nd Floor, Old Sachivalaya, Gandhinagar - 382010"),
    ("Dr. Ambedkar Antyodaya Vikas Nigam", "Gujarat", "Karmayogi Bhavan, Block 2, D2 Wing, 4th Floor, Block-10, Gandhinagar"),
    ("Goa State SC & OBC Finance and Development Corporation Ltd", "Goa", "4th Floor, Patto Centre, Near Kadamba Bus Stand, Panaji, Goa - 403001"),
    ("Haryana Scheduled Castes Finance & Development Corporation Ltd (HSFDC)", "Haryana", "SCO-2427-28, Sector-22-C, Chandigarh - 160022"),
    ("Himachal Pradesh SC-ST Development Corporation", "Himachal Pradesh", "Kalyan Bhavan, Near Ambusha Resort, Solan - 173212"),
    ("Jharkhand State Scheduled Castes Cooperative Development Corporation", "Jharkhand", "Kalyan Complex, 3rd Floor, Baliyar Road, Ranchi - 834008"),
    ("J&K SC, ST and OBC Development Corporation Ltd", "Jammu and Kashmir", "Exchange Road, Near Red Cross Office, Srinagar - 190001"),
    ("Dr. B.R. Ambedkar Development Corporation Ltd", "Karnataka", "9th & 10th Floor, Vishweshwaraiah Mini Tower, Dr Ambedkar Veedhi, Bengaluru - 560001"),
    ("Kerala State SC & ST Development Corporation Ltd (KSDC)", "Kerala", "Town Hall Road, Thrissur - 680020"),
    ("Kerala State Women's Development Corporation", "Kerala", "1st Floor, Parvin Bhavan, East Fort, Attukulangara, Thiruvananthapuram - 695023"),
    ("MP State Cooperative Scheduled Castes Finance & Development Corporation", "Madhya Pradesh", "Rajiv Gandhi Bhavan, 35, Shyamla Hills, Bhopal - 462011"),
    ("Mahatma Phule Backward Class Development Corporation Ltd", "Maharashtra", "1-N, Supreme Shopping Centre, Gulmohar Cross Road No.9, JVPD Scheme, Juhu, Mumbai - 400049"),
    ("Sahityaratna Lokshahir Annabhau Sathe Vikas Nigam Ltd", "Maharashtra", "New Administrative Building-2, 3rd Floor, Ramkrishna Chemburkar Marg, Chembur (E), Mumbai - 400071"),
    ("Sant Rohidas Charmodyog and Charmakar Vikas Nigam", "Maharashtra", "Bombay Life Building, 5th Floor, 45, Veer Nariman Road, Mumbai - 400001"),
    ("Manipur Tribal Development Corp Ltd", "Manipur", "Lamphelpat, Imphal - 795004"),
    ("Manipur SC and ST Cooperative Development Bank", "Manipur", "Nambul Lamba, Stadium Road, Imphal East, Manipur - 795001"),
    ("Meghalaya Cooperative Apex Bank Ltd (MCAB)", "Meghalaya", "MG Road, Kacheri, Shillong - 793001"),
    ("Odisha SC & ST Development Finance Cooperative Corporation Ltd (OSFDC)", "Odisha", "Lewis Road, Bhubaneswar - 751014"),
    ("Puducherry Adi Dravidar Development Corporation Ltd", "Puducherry", "3rd Floor, Adi Dravidar Welfare Department, Thattanchavady, Puducherry - 605009"),
    ("Punjab Scheduled Castes Land Development & Finance Corporation", "Punjab", "SCO-101-102-103, Sector 17-D, Chandigarh - 160017"),
    ("Rajasthan SC and ST Finance & Development Cooperative Corporation Ltd", "Rajasthan", "3rd Floor, Central Block, Nehru Sahakar Bhavan, Bhawani Singh Marg, Jaipur - 302005"),
    ("Tamil Nadu Adi Dravidar Housing and Development Corporation Ltd (TAHDCO)", "Tamil Nadu", "31, Santhome Road, 2nd Lane, Teynampet, Chennai - 600018"),
    ("Tripura Scheduled Castes Cooperative Development Corporation Ltd", "Tripura", "Krishna Nagar PO, Lake Chowmuhani, Tripura - 799001"),
    ("UP Scheduled Castes Finance & Development Corporation Ltd", "Uttar Pradesh", "B-912, Sector, Mahanagar, Lucknow - 226006"),
    ("Uttarakhand Multipurpose Finance & Development Corporation", "Uttarakhand", "Directorate of Tribal Affairs, Bhagat Singh Colony, Dehradun - 248001"),
    ("West Bengal SC/ST/OBC Development & Finance Corporation (WBSCSTOBCDFC)", "West Bengal", "CF 217/A/1 Nabin Sarani, Sector-I, Salt Lake, Kolkata - 700064"),
    ("Dadra & Nagar Haveli / Daman & Diu SC/ST/OBC and Minorities Finance and Development Corporation", "Dadra and Nagar Haveli and Daman and Diu", "Near Electricity Department, 66 KVA Road, Silvassa - 396230"),
    ("Sikkim SC-ST and Backward Classes Development Corporation (SSCSTBCDC)", "Sikkim", "Bhanupath, Gangtok, Sikkim - 737101"),
    ("Mizoram Urban Cooperative Development Bank Ltd", "Mizoram", "Lalsawmliana Building (Top Floor), Zarkawt, Aizawl - 796001"),
    ("Mizoram Khadi & Village Industries Board", "Mizoram", "Zarkawt, Aizawl - 796007"),
    ("UP Cooperative Gram Vikas Bank Ltd", "Uttar Pradesh", "10, Mall Avenue, Lucknow, Uttar Pradesh - 226001"),
]
for name, state, addr in sca_data:
    add(name, "SCA", state, addr, SCA)

# --- 2. Regional Rural Banks (41) ---
rrb_data = [
    ("Dakshin Bihar Gramin Bank", "Bihar", "Ashok Rajpath, Near BP Highways Petrol Pump, Patna - 800016"),
    ("Uttar Bihar Gramin Bank", "Bihar", "Kalambag Chowk, Muzaffarpur - 842001"),
    ("Jharkhand Rajya Gramin Bank", "Jharkhand", "Near Nagar Palika Chowk, Dumka, Jharkhand"),
    ("Maharashtra Gramin Bank", "Maharashtra", "Plot No.35, Jeevan Shree Town Centre, CIDCO - 431003"),
    ("Vidarbha Konkan Gramin Bank", "Maharashtra", "Chandraprastha, Plot No 6, Ring Road, Nagpur - 440022"),
    ("Sarva Haryana Gramin Bank", "Haryana", "Near Bajrang Bhavan, Delhi Road, Rohtak - 124001"),
    ("Baroda Gujarat Gramin Bank", "Gujarat", "Skyline Building, 2nd Floor, Near Sheetal Guest House, Bharuch - 392001"),
    ("Telangana Gramin Bank", "Telangana", "House No 2-1-520, Nallakunta, Hyderabad - 500044"),
    ("Rajasthan Marudhara Gramin Bank", "Rajasthan", "Tulsi Tower, 9th, B Road, Sardarpura, Jodhpur - 342003"),
    ("Baroda UP Gramin Bank", "Uttar Pradesh", "A-1, Civil Lines, Rae Bareli - 229001"),
    ("Kerala Gramin Bank", "Kerala", "PB No.10, KGPB Towers, Aluva, Kerala - 683101"),
    ("Uttarakhand Gramin Bank", "Uttarakhand", "18-A, Uttarakhand"),
    ("Prathama UP Gramin Bank", "Uttar Pradesh", "Prathama Bhavan, Ram Ganga Vihar-II, Moradabad - 244001"),
    ("Karnataka Gramin Bank", "Karnataka", "CA 20, Vijayanagar II Stage, Mysore - 570017"),
    ("Tripura Gramin Bank", "Tripura", "Airport Road, PO Abhoynagar, Agartala, Tripura (West) - 799005"),
    ("Chaitanya Godavari Gramin Bank", "Andhra Pradesh", "4th Floor, Raghumandan, 4-1, Brodipet, Guntur - 522002"),
    ("Karnataka Vikas Gramin Bank", "Karnataka", "PB No. 111, Dharwad - 580008"),
    ("Assam Gramin Vikas Bank", "Assam", "GS Road, Bhangagarh, Guwahati - 781005"),
    ("Tamil Nadu Grama Bank", "Tamil Nadu", "6, Yercaud Road, Hasthampatti, Salem - 636007"),
    ("Punjab Gramin Bank", "Punjab", "Jalandhar Road, Kapurthala - 144601"),
    ("Madhyanchal Gramin Bank", "Madhya Pradesh", "Poddar Colony, Tili Road, Sagar - 470001"),
    ("Aryavart Bank", "Uttar Pradesh", "A-2/46, Vijay Khand, Gomti Nagar, Lucknow - 226010"),
    ("Andhra Pradesh Grameena Vikas Bank", "Andhra Pradesh", "Door No.2-5-8/1, Ramnagar, Hanmakonda, Warangal - 506001"),
    ("Saptagiri Grameena Bank", "Andhra Pradesh", "PB17, Naidu Buildings, Chittoor - 517001"),
    ("Himachal Pradesh Gramin Bank", "Himachal Pradesh", "Jail Road, PO Talyahar, Mandi - 175001"),
    ("Madhya Pradesh Gramin Bank", "Madhya Pradesh", "43, Khajrana Road, Peepal Chowk, Ganeshpuri, Indore - 452016"),
    ("Puduvai Bharathiar Grama Bank", "Puducherry", "441, Mahatma Gandhi Road, Muthialpet, Puducherry - 605003"),
    ("Andhra Pragathi Grameena Bank", "Andhra Pradesh", "Mariyapuram, Kadapa - 516003"),
    ("Saurashtra Gramin Bank", "Gujarat", "LIC Jeevan Prakash Building, Tagore Marg, Rajkot - 360001"),
    ("Paschim Banga Gramin Bank", "West Bengal", "Natabar Paul Road, Tikiyapara, Howrah - 711101"),
    ("Baroda Rajasthan Kshetriya Gramin Bank", "Rajasthan", "Plot Number-2343, Anna Sagar Circular Road, Ajmer - 305004"),
    ("Manipur Rural Bank", "Manipur", "Imphal - 795001"),
    ("Chhattisgarh Rajya Gramin Bank", "Chhattisgarh", "Mahadevghat Road, Sundar Nagar, Raipur - 492013"),
    ("Jammu & Kashmir Grameen Vikas Bank", "Jammu and Kashmir", "Near J&K Wool Complex, Narwal - 180006"),
    ("Ellaquai Dehati Bank", "Jammu and Kashmir", "3rd Floor, Nirman Complex, Airport (IG) Road, Barzulla, Srinagar - 190005"),
    ("Mizoram Rural Bank", "Mizoram", "Minco, Aizawl - 796001"),
    ("Meghalaya Rural Bank", "Meghalaya", "MTC Bhavan, 2nd Floor, Police Bazar, Shillong - 793001"),
    ("Utkal Gramin Bank", "Odisha", "Doorsanchar Bhavan, Near New Bus Stand, Bolangir - 767001"),
    ("Bangiya Gramin Vikash Bank", "West Bengal", "BMC House, NH-34, Chaltiya, Chuanpur, PO Berhampore - 742101"),
    ("Uttarbanga Kshetriya Gramin Bank", "West Bengal", "Sanit Road, Cooch Behar - 736101"),
    ("Odisha Gramya Bank", "Odisha", "Sponsored by Indian Overseas Bank, Odisha"),
]
for name, state, addr in rrb_data:
    add(name, "RRB", state, addr, BANK)

# --- 3. NBFC-MFI (7) ---
nbfc_data = [
    ("Ananya Finance for Inclusive Growth Pvt Ltd", "Maharashtra", "'Sahyadri Building', Behind Amiteish Hotel, Ambajogai Road, Sai Naka, Latur - 413512"),
    ("Grameen Development and Finance Pvt Ltd", "Assam", "Dabjent, Kundil Road, Chaygaon, Kamrup - 781124"),
    ("ASA International Microfinance Ltd", "West Bengal", "Victoria Park, 4th Floor, GN-37/2, Sector-V, Salt Lake City, Kolkata - 700091"),
    ("Midland Microfin Limited", "Punjab", "The Exist, Plot No.1, R.B. Badri Dass Colony, BMC Chowk, GT Road, Jalandhar - 144001"),
    ("Satin Creditcare Network Limited", "Haryana", "Plot No.492, Udyog Vihar, Phase-III, Gurugram - 122016"),
    ("Pahal Financial Services Pvt Ltd", "Gujarat", "7th Floor, Binori B Square-2, Ambli-Iscon Road, Ahmedabad - 380054"),
    ("Vector Finance Pvt Ltd", "Odisha", "K7/110, Ground Floor, Kalinga Vihar, PS Khandagiri, Bhubaneswar - 751029"),
]
for name, state, addr in nbfc_data:
    add(name, "NBFC-MFI", state, addr, MFI)

# --- 4. Cooperative Societies (4) ---
coop_data = [
    ("Shri Mahila Seva Sahakari Bank Ltd", "Gujarat", "109, Sakar-II, Town Hall Road, Ellisbridge, Ahmedabad - 380006"),
    ("Konkalata Mahila Shahari Sahakari Bank", "Assam", "Assam"),
    ("Streenidhi Telangana", "Telangana", "401 & 402, 4th Floor, My Home Sarovar Plaza, Secretariat Road, Ambedkar Colony, Saifabad, Hyderabad - 500004"),
    ("Streenidhi AP", "Andhra Pradesh", "2nd Floor, NTR Administrative Block, RTC Complex, Vijayawada - 520013"),
]
for name, state, addr in coop_data:
    add(name, "Cooperative Society", state, addr, MFI)

# --- 5. Public Sector Banks (11) ---
psb_data = [
    ("Indian Overseas Bank", "Tamil Nadu", "Central Office, 763, Anna Salai, Chennai - 600002"),
    ("Bank of Baroda", "Gujarat", "Baroda Bhavan, 7th Floor, R.C. Dutt Road, Vadodara - 390007"),
    ("Canara Bank", "Karnataka", "Head Office, 112, J.C. Road, Bengaluru - 560002"),
    ("Punjab National Bank", "Delhi", "Plot No.-4, Sector 10, Dwarka, New Delhi - 110075"),
    ("Punjab & Sind Bank", "Delhi", "Priority Sector Advance Department, 5th Floor, 21 Rajendra Place, New Delhi - 110008"),
    ("Union Bank of India", "Maharashtra", "Central Office, Union Bank Bhavan, Nariman Point, Mumbai"),
    ("Indian Bank", "Tamil Nadu", "Corporate Office, No.254-260, Avvai Shanmugam Salai, Royapettah, Chennai - 600014"),
    ("Bank of Maharashtra", "Maharashtra", "Head Office 'Lokmangal', 1501, Shivajinagar, Pune - 411005"),
    ("Bank of India", "Maharashtra", "Bandra Kurla Complex, Bandra (East), Mumbai - 400051"),
    ("Central Bank of India", "Maharashtra", "Chandermukhi Bldg., Nariman Point, Mumbai - 400021"),
    ("UCO Bank", "West Bengal", "No 3&4, DD Block, Sector-1, Bidhannagar, Kolkata - 700064"),
]
for name, state, addr in psb_data:
    add(name, "PSB", state, addr, BANK)

# --- 6. Small Finance Banks (2) ---
add("AU Small Finance Bank", "Small Finance Bank", "Rajasthan", "Jaipur, Rajasthan", ["micro_finance", "term_loan"])
add("Ujjivan Small Finance Bank", "Small Finance Bank", "Karnataka", "Bengaluru, Karnataka", ["micro_finance", "term_loan"])

# --- 7. Other Agencies (3) - sector-specific mapping ---
add("North Eastern Development Finance Corporation Ltd (NEDFi)", "Other Agency", "Assam",
    "Tea Auction Center, GS Road, Sanket Vihar, Dispur, Guwahati - 781006", SCA)  # regional, all categories for NE
add("Jharkhand Silk Textile & Handicraft Development Corporation Ltd (JHARCRAFT)", "Other Agency", "Jharkhand",
    "DIC Campus, Ratu Road, Ranchi - 834001", MFI)  # artisan/handicraft -> micro finance
add("Small Industries Development Bank of India (SIDBI)", "Other Agency", "Uttar Pradesh",
    "SIDBI Tower, 15, Ashok Marg, Lucknow - 226001", ["term_loan"])  # industrial -> term loans

print(f"Total partners built: {len(partners)}")
type_counts = {}
for p in partners:
    type_counts[p['type']] = type_counts.get(p['type'], 0) + 1
print("By type:", type_counts)

with open('/home/claude/channel_partners.json', 'w', encoding='utf-8') as f:
    json.dump(partners, f, indent=2, ensure_ascii=False)
print("Saved to channel_partners.json")
