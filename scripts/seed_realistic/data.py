"""The demo data: Cambodian pharmacy medicines, people, places. Khmer names are transliterations for a demo
(have a Khmer-speaking pharmacist review them before showing real users). Prices are typical retail USD."""

# --- catalog --------------------------------------------------------------------------------------------
# (code, name_en, name_km)
CATEGORIES = [
    ("PAIN", "Pain & fever", "ឈឺចាប់ និងគ្រុនក្តៅ"),
    ("ABX", "Antibiotics", "ថ្នាំអង់ទីប៊ីយោទិក"),
    ("HEART", "Heart & blood pressure", "បេះដូង និងសម្ពាធឈាម"),
    ("DIAB", "Diabetes", "ទឹកនោមផ្អែម"),
    ("GI", "Stomach & digestion", "ក្រពះ និងរំលាយអាហារ"),
    ("RESP", "Cough, cold & allergy", "ក្អក ផ្តាសាយ និងអាឡែស៊ី"),
    ("VIT", "Vitamins & supplements", "វីតាមីន និងអាហារបំប៉ន"),
    ("SKIN", "Skin care", "ថែរក្សាស្បែក"),
    ("EYE", "Eye & ear", "ភ្នែក និងត្រចៀក"),
    ("PARA", "Worms & malaria", "ព្រូន និងគ្រុនចាញ់"),
    ("NERVE", "Nerves & sleep", "សរសៃប្រសាទ និងដំណេក"),
    ("WOMEN", "Women's health", "សុខភាពស្ត្រី"),
    ("FIRST", "First aid", "សង្គ្រោះបឋម"),
]

BRANDS = [  # (name_en, name_km)
    ("GSK", "ជីអេសខេ"), ("Sanofi", "សាណូហ្វី"), ("Pfizer", "ហ្វាយហ្សឺ"), ("Bayer", "បាយ៉ឺ"),
    ("Abbott", "អាបូត"), ("Novartis", "ណូវ៉ាទីស"), ("Unilab", "យូនីឡាប"), ("Mega We Care", "មេហ្គា"),
    ("Medochemie", "មេដូឃីមី"), ("Stada", "ស្តាដា"), ("Siam Pharma", "សៀមហ្វាម៉ា"),
    ("Cambodia Pharma", "កម្ពុជាហ្វាម៉ា"), ("Hasan", "ហាសាន"), ("Domesco", "ដូមេស្កូ"), ("Reckitt", "រ៉េគីត"),
]

# One row per medicine:
# sku, brand, generic, strength, form, Khmer, category, brand_owner, rx, schedule, classes, base_unit, base_price,
# packs ((name, qty_in_base, price) …), popularity (relative sales weight)
T = "tablet"
C = "capsule"
MEDICINES = [
    # pain & fever
    ("PARA500", "Panadol", "Paracetamol", "500 mg", T, "ប៉ារ៉ាសេតាម៉ុល", "PAIN", "GSK", False, None, ["analgesics"], T, 0.10, (("strip", 10, 0.90), ("box", 120, 9.50)), 30),
    ("PARA650", "Panadol Extra", "Paracetamol + Caffeine", "500/65 mg", T, "ប៉ារ៉ាសេតាម៉ុល អិចស្ត្រា", "PAIN", "GSK", False, None, ["analgesics"], T, 0.15, (("strip", 12, 1.60), ("box", 96, 12.00)), 14),
    ("SARA500", "Sara", "Paracetamol", "500 mg", T, "សារ៉ា", "PAIN", "Siam Pharma", False, None, ["analgesics"], T, 0.06, (("strip", 10, 0.55), ("box", 100, 5.00)), 18),
    ("CALPOL", "Calpol syrup", "Paracetamol", "120 mg/5 ml", "syrup", "កាល់ប៉ុល ទឹកស៊ីរ៉ូ", "PAIN", "GSK", False, None, ["analgesics"], "bottle", 3.20, (), 9),
    ("IBU400", "Brufen", "Ibuprofen", "400 mg", T, "អ៊ីប៊ុយប្រូហ្វេន", "PAIN", "Abbott", False, None, ["nsaids"], T, 0.12, (("strip", 10, 1.10), ("box", 100, 10.00)), 12),
    ("IBU200", "Advil", "Ibuprofen", "200 mg", T, "អាដវីល", "PAIN", "Pfizer", False, None, ["nsaids"], T, 0.09, (("strip", 10, 0.85),), 6),
    ("MEFE500", "Ponstan", "Mefenamic acid", "500 mg", T, "ម៉េហ្វេណាមិច", "PAIN", "Pfizer", False, None, ["nsaids"], T, 0.15, (("strip", 10, 1.40), ("box", 100, 13.00)), 7),
    ("DICLO50", "Voltaren", "Diclofenac", "50 mg", T, "ឌីក្លូហ្វេណាក", "PAIN", "Novartis", True, None, ["nsaids"], T, 0.18, (("strip", 10, 1.70), ("box", 100, 16.00)), 5),
    ("ASP81", "Aspilets", "Aspirin", "80 mg", T, "អាស្ពីរីន", "PAIN", "Unilab", False, None, ["nsaids", "antiplatelets"], T, 0.05, (("strip", 10, 0.45), ("box", 100, 4.00)), 4),
    ("NAPRO250", "Naprosyn", "Naproxen", "250 mg", T, "ណាប្រូហ្សែន", "PAIN", "Stada", False, None, ["nsaids"], T, 0.16, (("strip", 10, 1.50),), 2),
    ("CELE200", "Celebrex", "Celecoxib", "200 mg", C, "សេឡេកុកស៊ីប", "PAIN", "Pfizer", True, None, ["nsaids"], C, 0.55, (("strip", 10, 5.20),), 2),
    ("MELOX75", "Mobic", "Meloxicam", "7.5 mg", T, "មេឡុកស៊ីកាម", "PAIN", "Stada", False, None, ["nsaids"], T, 0.20, (("strip", 10, 1.90),), 3),
    ("TRAM50", "Tramal", "Tramadol", "50 mg", C, "ត្រាម៉ាដុល", "PAIN", "Stada", True, "IV", ["opioids"], C, 0.35, (("strip", 10, 3.30),), 1),
    # antibiotics (Rx)
    ("AMOX500", "Amoxil", "Amoxicillin", "500 mg", C, "អាម៉ុកស៊ីស៊ីលីន", "ABX", "GSK", True, None, ["penicillins"], C, 0.12, (("strip", 10, 1.10), ("box", 100, 10.50)), 10),
    ("AUGM625", "Augmentin", "Amoxicillin + Clavulanic acid", "500/125 mg", T, "អូហ្គម៉ង់ទីន", "ABX", "GSK", True, None, ["penicillins"], T, 0.65, (("strip", 7, 4.40), ("box", 14, 8.50)), 6),
    ("AZI500", "Zithromax", "Azithromycin", "500 mg", T, "អាហ្ស៊ីត្រូម៉ាយស៊ីន", "ABX", "Pfizer", True, None, ["macrolides"], T, 1.10, (("strip", 3, 3.20),), 6),
    ("CEFA500", "Keflex", "Cefalexin", "500 mg", C, "សេហ្វាឡិចស៊ីន", "ABX", "Medochemie", True, None, ["cephalosporins"], C, 0.20, (("strip", 10, 1.90), ("box", 100, 18.00)), 4),
    ("CEFI200", "Suprax", "Cefixime", "200 mg", C, "សេហ្វីស៊ីម", "ABX", "Hasan", True, None, ["cephalosporins"], C, 0.70, (("strip", 10, 6.80),), 3),
    ("CIPRO500", "Ciprobay", "Ciprofloxacin", "500 mg", T, "ស៊ីប្រូហ្វ្លុកសាស៊ីន", "ABX", "Bayer", True, None, ["fluoroquinolones"], T, 0.25, (("strip", 10, 2.40),), 4),
    ("DOXY100", "Doxyn", "Doxycycline", "100 mg", C, "ដុកស៊ីស៊ីគ្លីន", "ABX", "Domesco", True, None, ["tetracyclines"], C, 0.10, (("strip", 10, 0.95),), 3),
    ("METRO250", "Flagyl", "Metronidazole", "250 mg", T, "មេត្រូនីដាហ្សូល", "ABX", "Sanofi", True, None, ["nitroimidazoles"], T, 0.06, (("strip", 10, 0.55), ("box", 100, 5.00)), 4),
    ("COTRI480", "Bactrim", "Sulfamethoxazole + Trimethoprim", "400/80 mg", T, "បាក់ទ្រីម", "ABX", "Domesco", True, None, ["sulfonamides"], T, 0.07, (("strip", 10, 0.65),), 2),
    ("AMOXSYR", "Amoxil syrup", "Amoxicillin", "250 mg/5 ml", "syrup", "អាម៉ុកស៊ីស៊ីលីន ទឹកស៊ីរ៉ូ", "ABX", "GSK", True, None, ["penicillins"], "bottle", 3.80, (), 3),
    # heart (Rx)
    ("AMLO5", "Norvasc", "Amlodipine", "5 mg", T, "អាំឡូឌីពីន", "HEART", "Pfizer", True, None, ["calcium channel blockers"], T, 0.15, (("strip", 10, 1.40), ("box", 30, 4.00)), 8),
    ("AMLO10", "Norvasc 10", "Amlodipine", "10 mg", T, "អាំឡូឌីពីន ១០", "HEART", "Pfizer", True, None, ["calcium channel blockers"], T, 0.22, (("strip", 10, 2.10),), 3),
    ("LOSA50", "Cozaar", "Losartan", "50 mg", T, "ឡូសាតង់", "HEART", "Stada", True, None, ["angiotensin receptor blockers"], T, 0.25, (("strip", 10, 2.40), ("box", 30, 6.90)), 5),
    ("ATOR20", "Lipitor", "Atorvastatin", "20 mg", T, "អាតូវ៉ាស្តាទីន", "HEART", "Pfizer", True, None, ["statins"], T, 0.40, (("strip", 10, 3.80), ("box", 30, 11.00)), 5),
    ("BISO5", "Concor", "Bisoprolol", "5 mg", T, "ប៊ីសូប្រូឡុល", "HEART", "Medochemie", True, None, ["beta blockers"], T, 0.20, (("strip", 10, 1.90),), 2),
    ("CLOPI75", "Plavix", "Clopidogrel", "75 mg", T, "ក្លូពីដូហ្គ្រែល", "HEART", "Sanofi", True, None, ["antiplatelets"], T, 0.60, (("strip", 10, 5.80),), 2),
    # diabetes (Rx)
    ("METF500", "Glucophage", "Metformin", "500 mg", T, "មេតហ្វរមីន", "DIAB", "Medochemie", True, None, ["biguanides"], T, 0.06, (("strip", 10, 0.55), ("box", 100, 5.20)), 9),
    ("METF850", "Glucophage 850", "Metformin", "850 mg", T, "មេតហ្វរមីន ៨៥០", "DIAB", "Medochemie", True, None, ["biguanides"], T, 0.09, (("strip", 10, 0.85),), 4),
    ("GLICL80", "Diamicron", "Gliclazide", "80 mg", T, "ហ្គ្លីក្លាហ្ស៊ីដ", "DIAB", "Stada", True, None, ["sulfonylureas"], T, 0.12, (("strip", 10, 1.10),), 3),
    # stomach
    ("OMEP20", "Losec", "Omeprazole", "20 mg", C, "អូមេប្រាហ្សូល", "GI", "Stada", False, None, ["proton pump inhibitors"], C, 0.12, (("strip", 10, 1.10), ("box", 100, 10.00)), 12),
    ("ESOM40", "Nexium", "Esomeprazole", "40 mg", T, "អេសូមេប្រាហ្សូល", "GI", "Stada", False, None, ["proton pump inhibitors"], T, 0.45, (("strip", 7, 3.00),), 4),
    ("FAMO20", "Pepcid", "Famotidine", "20 mg", T, "ហ្វាម៉ូទីឌីន", "GI", "Domesco", False, None, ["h2 blockers"], T, 0.08, (("strip", 10, 0.75),), 3),
    ("DOMP10", "Motilium", "Domperidone", "10 mg", T, "ដុមភេរីដូន", "GI", "Stada", False, None, ["antiemetics"], T, 0.10, (("strip", 10, 0.95), ("box", 100, 9.00)), 7),
    ("LOPE2", "Imodium", "Loperamide", "2 mg", C, "ឡូប៉េរ៉ាមីដ", "GI", "Stada", False, None, ["antidiarrhoeals"], C, 0.15, (("strip", 10, 1.40),), 6),
    ("ORS", "Oresol", "Oral rehydration salts", "20.5 g", "sachet", "អូរ៉េសូល", "GI", "Cambodia Pharma", False, None, ["electrolytes"], "sachet", 0.25, (("box", 20, 4.50),), 14),
    ("SMECTA", "Smecta", "Diosmectite", "3 g", "sachet", "ស្មិចតា", "GI", "Stada", False, None, ["antidiarrhoeals"], "sachet", 0.40, (("box", 30, 11.00),), 5),
    ("GAVIS", "Gaviscon", "Sodium alginate + antacids", "10 ml", "sachet", "ហ្គាវីស្កុន", "GI", "Reckitt", False, None, ["antacids"], "sachet", 0.45, (("box", 24, 10.00),), 6),
    ("BUSCO10", "Buscopan", "Hyoscine butylbromide", "10 mg", T, "ប៊ុស្កូប៉ាន", "GI", "Sanofi", False, None, ["antispasmodics"], T, 0.18, (("strip", 10, 1.70), ("box", 100, 16.00)), 6),
    ("BISA5", "Dulcolax", "Bisacodyl", "5 mg", T, "ឌុលកូឡាក់", "GI", "Sanofi", False, None, ["laxatives"], T, 0.10, (("strip", 10, 0.95),), 3),
    ("SIME40", "Air-X", "Simethicone", "40 mg", T, "ស៊ីមេទីកូន", "GI", "Mega We Care", False, None, ["antiflatulents"], T, 0.08, (("strip", 10, 0.75),), 4),
    ("ANTAC", "Kremil-S", "Aluminium + magnesium hydroxide", "", T, "ក្រេមីល អេស", "GI", "Unilab", False, None, ["antacids"], T, 0.07, (("strip", 10, 0.65), ("box", 100, 6.00)), 6),
    # cough, cold, allergy
    ("CETI10", "Zyrtec", "Cetirizine", "10 mg", T, "សេទីរីហ្ស៊ីន", "RESP", "GSK", False, None, ["antihistamines"], T, 0.12, (("strip", 10, 1.10), ("box", 100, 10.00)), 12),
    ("LORA10", "Clarityne", "Loratadine", "10 mg", T, "ឡូរ៉ាតាឌីន", "RESP", "Bayer", False, None, ["antihistamines"], T, 0.15, (("strip", 10, 1.40),), 7),
    ("CHLOR4", "Piriton", "Chlorphenamine", "4 mg", T, "ក្លរហ្វេណាមីន", "RESP", "GSK", False, None, ["antihistamines"], T, 0.03, (("strip", 10, 0.25), ("box", 100, 2.20)), 6),
    ("FEXO180", "Telfast", "Fexofenadine", "180 mg", T, "ហ្វិចសូហ្វេណាឌីន", "RESP", "Sanofi", False, None, ["antihistamines"], T, 0.40, (("strip", 10, 3.80),), 3),
    ("AMBRO30", "Mucosolvan", "Ambroxol", "30 mg", T, "អាំប្រុកសុល", "RESP", "Sanofi", False, None, ["mucolytics"], T, 0.08, (("strip", 10, 0.75), ("box", 100, 7.00)), 7),
    ("BROM8", "Bisolvon", "Bromhexine", "8 mg", T, "ប្រូមហិចស៊ីន", "RESP", "Sanofi", False, None, ["mucolytics"], T, 0.07, (("strip", 10, 0.65),), 4),
    ("DECOL", "Decolgen", "Paracetamol + Phenylephrine + Chlorphenamine", "", T, "ដេកូលហ្សែន", "RESP", "Unilab", False, None, ["analgesics", "decongestants"], T, 0.12, (("strip", 4, 0.45), ("box", 100, 10.50)), 14),
    ("TIFFY", "Tiffy", "Paracetamol + Phenylephrine + Chlorphenamine", "", T, "ធីហ្វី", "RESP", "Siam Pharma", False, None, ["analgesics", "decongestants"], T, 0.10, (("strip", 4, 0.40),), 10),
    ("COUGHSYR", "Robitussin", "Dextromethorphan + Guaifenesin", "60 ml", "syrup", "រ៉ូប៊ីទូស៊ីន", "RESP", "Pfizer", False, None, ["antitussives"], "bottle", 3.50, (), 7),
    ("STREP", "Strepsils", "Amylmetacresol + Dichlorobenzyl alcohol", "", "lozenge", "ស្ត្រេបស៊ីល", "RESP", "Reckitt", False, None, ["antiseptics"], "lozenge", 0.12, (("strip", 8, 0.90), ("box", 24, 2.60)), 9),
    ("SALBINH", "Ventolin inhaler", "Salbutamol", "100 mcg", "inhaler", "វេនតូលីន", "RESP", "GSK", True, None, ["bronchodilators"], "inhaler", 4.50, (), 3),
    ("MONTE10", "Singulair", "Montelukast", "10 mg", T, "ម៉ុនតេលូកាស", "RESP", "Stada", True, None, ["leukotriene antagonists"], T, 0.45, (("strip", 10, 4.30),), 1),
    ("PRED5", "Prednisolone", "Prednisolone", "5 mg", T, "ព្រេដនីសូឡូន", "RESP", "Domesco", True, None, ["corticosteroids"], T, 0.04, (("strip", 10, 0.35), ("box", 100, 3.20)), 3),
    # vitamins
    ("VITC500", "Ceelin", "Ascorbic acid", "500 mg", T, "វីតាមីន C", "VIT", "Unilab", False, None, ["vitamins"], T, 0.06, (("strip", 10, 0.55), ("box", 100, 5.00)), 12),
    ("VITB", "Neurobion", "Vitamin B1 + B6 + B12", "", T, "ណឺរ៉ូប៊ីយ៉ុង", "VIT", "Bayer", False, None, ["vitamins"], T, 0.20, (("strip", 10, 1.90), ("box", 100, 18.00)), 9),
    ("CENTRUM", "Centrum", "Multivitamins + minerals", "", T, "សេនទ្រុម", "VIT", "Pfizer", False, None, ["vitamins"], T, 0.30, (("bottle", 30, 8.50),), 5),
    ("CALD3", "Caltrate", "Calcium carbonate + Vitamin D3", "600 mg/400 IU", T, "កាល់ទ្រេត", "VIT", "Pfizer", False, None, ["minerals"], T, 0.20, (("bottle", 60, 11.00),), 5),
    ("FERRO", "Ferrovit", "Ferrous fumarate + Folic acid", "", C, "ហ្វេរ៉ូវីត", "VIT", "Mega We Care", False, None, ["minerals"], C, 0.10, (("strip", 10, 0.95), ("box", 100, 9.00)), 6),
    ("FOLIC5", "Folic acid", "Folic acid", "5 mg", T, "អាស៊ីតហ្វូលិក", "VIT", "Cambodia Pharma", False, None, ["vitamins"], T, 0.02, (("strip", 10, 0.18), ("box", 100, 1.60)), 4),
    ("ZINC20", "Zinc", "Zinc sulfate", "20 mg", T, "ស័ង្កសី", "VIT", "Cambodia Pharma", False, None, ["minerals"], T, 0.05, (("strip", 10, 0.45),), 4),
    ("VITE400", "Natural E", "Vitamin E", "400 IU", C, "វីតាមីន E", "VIT", "Mega We Care", False, None, ["vitamins"], C, 0.15, (("strip", 10, 1.40), ("box", 30, 4.00)), 4),
    ("FISHOIL", "Omega-3 fish oil", "Fish oil", "1000 mg", C, "ប្រេងត្រី អូមេហ្គា ៣", "VIT", "Mega We Care", False, None, ["supplements"], C, 0.12, (("bottle", 100, 11.00),), 3),
    ("BEROCCA", "Berocca", "Vitamin B + C + minerals", "", "effervescent", "បេរ៉ូកា", "VIT", "Bayer", False, None, ["vitamins"], "tablet", 0.50, (("tube", 10, 4.80),), 4),
    ("OBIMIN", "Obimin", "Prenatal multivitamins", "", T, "អូប៊ីមីន", "VIT", "Unilab", False, None, ["vitamins"], T, 0.15, (("strip", 10, 1.40), ("box", 30, 4.00)), 3),
    ("ENERVON", "Enervon", "Multivitamins", "", T, "អេណឺវ៉ុន", "VIT", "Unilab", False, None, ["vitamins"], T, 0.10, (("strip", 10, 0.95), ("box", 100, 9.00)), 5),
    # skin
    ("CLOTRI", "Canesten", "Clotrimazole", "1% 20 g", "cream", "ក្លូទ្រីម៉ាហ្សូល", "SKIN", "Bayer", False, None, ["antifungals"], "tube", 2.80, (), 5),
    ("HYDROC", "Hydrocortisone", "Hydrocortisone", "1% 15 g", "cream", "អ៊ីដ្រូកូទីសូន", "SKIN", "Medochemie", False, None, ["corticosteroids"], "tube", 1.50, (), 3),
    ("BETADINE", "Betadine", "Povidone-iodine", "10% 30 ml", "solution", "បេតាឌីន", "SKIN", "Mega We Care", False, None, ["antiseptics"], "bottle", 1.90, (), 8),
    ("CALAM", "Calamine lotion", "Calamine + Zinc oxide", "120 ml", "lotion", "កាឡាមីន", "SKIN", "Cambodia Pharma", False, None, ["antipruritics"], "bottle", 1.60, (), 3),
    ("FUCID", "Fucidin", "Fusidic acid", "2% 15 g", "cream", "ហ្វូស៊ីឌីន", "SKIN", "Stada", False, None, ["antibacterials"], "tube", 4.20, (), 3),
    ("ACYCR", "Zovirax cream", "Aciclovir", "5% 5 g", "cream", "អាស៊ីក្លូវៀរ", "SKIN", "GSK", False, None, ["antivirals"], "tube", 3.50, (), 2),
    ("KETOSH", "Nizoral shampoo", "Ketoconazole", "2% 100 ml", "shampoo", "ណីហ្សូរ៉ាល", "SKIN", "Stada", False, None, ["antifungals"], "bottle", 6.50, (), 2),
    ("TIGER", "Tiger Balm", "Camphor + Menthol", "19 g", "ointment", "ប្រេងខ្លា", "SKIN", "Hasan", False, None, ["rubefacients"], "jar", 2.20, (), 8),
    ("EUCA", "Eucalyptus oil", "Eucalyptus oil", "25 ml", "oil", "ប្រេងអេកាលីបទុស", "SKIN", "Hasan", False, None, ["rubefacients"], "bottle", 1.80, (), 5),
    # eye & ear
    ("CHLOREYE", "Chloramphenicol eye drops", "Chloramphenicol", "0.5% 10 ml", "eye drops", "ក្លរ៉ាមហ្វេនីកុល ដាក់ភ្នែក", "EYE", "Domesco", True, None, ["amphenicols"], "bottle", 1.20, (), 3),
    ("TEARS", "Systane", "Artificial tears", "10 ml", "eye drops", "ទឹកភ្នែកសិប្បនិម្មិត", "EYE", "Novartis", False, None, ["lubricants"], "bottle", 5.50, (), 3),
    ("TOBRA", "Tobrex", "Tobramycin", "0.3% 5 ml", "eye drops", "តូប្រាម៉ាយស៊ីន", "EYE", "Novartis", True, None, ["aminoglycosides"], "bottle", 3.80, (), 2),
    # worms & malaria
    ("MEBEN", "Vermox", "Mebendazole", "500 mg", T, "មេបេនដាហ្សូល", "PARA", "Stada", False, None, ["anthelmintics"], T, 0.50, (), 5),
    ("ALBEN", "Zentel", "Albendazole", "400 mg", T, "អាល់បេនដាហ្សូល", "PARA", "GSK", False, None, ["anthelmintics"], T, 0.60, (), 6),
    ("COARTEM", "Coartem", "Artemether + Lumefantrine", "20/120 mg", T, "កូអាតឹម", "PARA", "Novartis", True, None, ["antimalarials"], T, 0.35, (("box", 24, 8.00),), 1),
    ("FLUCO150", "Diflucan", "Fluconazole", "150 mg", C, "ហ្វ្លូកូណាហ្សូល", "WOMEN", "Pfizer", True, None, ["antifungals"], C, 1.20, (), 3),
    # nerves & sleep
    ("DIAZ5", "Valium", "Diazepam", "5 mg", T, "ឌីយ៉ាហ្សេប៉ាម", "NERVE", "Medochemie", True, "IV", ["benzodiazepines"], T, 0.10, (("strip", 10, 0.90),), 1),
    ("PHENO30", "Luminal", "Phenobarbital", "30 mg", T, "ហ្វេណូបាបីតាល់", "NERVE", "Medochemie", True, "IV", ["barbiturates"], T, 0.08, (("strip", 10, 0.70),), 1),
    ("BETAH16", "Serc", "Betahistine", "16 mg", T, "បេតាហ៊ីស្ទីន", "NERVE", "Stada", False, None, ["antivertigo"], T, 0.15, (("strip", 10, 1.40),), 3),
    ("DIMEN50", "Dramamine", "Dimenhydrinate", "50 mg", T, "ឌីមេនហ៊ីដ្រីណាត", "NERVE", "Domesco", False, None, ["antihistamines"], T, 0.05, (("strip", 10, 0.45),), 4),
    # women's health
    ("MICROG", "Microgynon", "Levonorgestrel + Ethinylestradiol", "0.15/0.03 mg", T, "មីក្រូជីណុង", "WOMEN", "Bayer", False, None, ["contraceptives"], "cycle", 1.50, (), 4),
    ("PREGTEST", "Pregnancy test", "hCG test strip", "", "test", "តេស្តមានផ្ទៃពោះ", "WOMEN", "Mega We Care", False, None, ["diagnostics"], "test", 1.00, (), 4),
    # first aid
    ("PLASTER", "Band-Aid", "Adhesive plasters", "", "plaster", "បង់បិទរបួស", "FIRST", "Reckitt", False, None, ["dressings"], "piece", 0.05, (("box", 100, 4.00),), 8),
    ("GAUZE", "Sterile gauze", "Gauze pads", "10 x 10 cm", "pad", "មារ៉ាស់", "FIRST", "Cambodia Pharma", False, None, ["dressings"], "pack", 0.40, (), 4),
    ("BANDAGE", "Elastic bandage", "Elastic bandage", "7.5 cm", "roll", "បង់រុំ", "FIRST", "Cambodia Pharma", False, None, ["dressings"], "roll", 1.20, (), 3),
    ("ALCOHOL", "Alcohol 70%", "Ethanol", "70% 500 ml", "solution", "អាល់កុល ៧០%", "FIRST", "Cambodia Pharma", False, None, ["antiseptics"], "bottle", 1.80, (), 6),
    ("COTTON", "Cotton wool", "Cotton wool", "50 g", "roll", "កប្បាស", "FIRST", "Cambodia Pharma", False, None, ["dressings"], "roll", 0.80, (), 3),
    ("SALINE", "Normal saline", "Sodium chloride", "0.9% 500 ml", "solution", "ទឹកអំបិល ០.៩%", "FIRST", "Cambodia Pharma", False, None, ["electrolytes"], "bottle", 1.00, (), 4),
    ("MASK", "Face mask", "Surgical mask", "", "mask", "ម៉ាស", "FIRST", "Mega We Care", False, None, ["protective"], "piece", 0.08, (("box", 50, 3.50),), 6),
    ("THERMO", "Digital thermometer", "Thermometer", "", "device", "ទែម៉ូម៉ែត្រ", "FIRST", "Mega We Care", False, None, ["devices"], "piece", 3.50, (), 2),
]

# A wider generic range (same generic, other strengths and makers): fills the catalog to ~150 like a real shelf.
EXTRA = [
    ("PARA500B", "Efferalgan", "Paracetamol", "500 mg", "effervescent", "អេហ្វេរ៉ាល់ហ្គង់", "PAIN", "Stada", 0.20, (("tube", 16, 3.00),), 4),
    ("PARA1G", "Panadol 1000", "Paracetamol", "1000 mg", T, "ប៉ារ៉ាសេតាម៉ុល ១០០០", "PAIN", "GSK", 0.20, (("strip", 10, 1.90),), 3),
    ("IBUSYR", "Brufen syrup", "Ibuprofen", "100 mg/5 ml", "syrup", "អ៊ីប៊ុយប្រូហ្វេន ទឹកស៊ីរ៉ូ", "PAIN", "Abbott", 3.60, (), 3),
    ("DICLGEL", "Voltaren gel", "Diclofenac", "1% 20 g", "gel", "វ៉ុលតារ៉ែន ជែល", "PAIN", "Novartis", 4.50, (), 5),
    ("SALONP", "Salonpas", "Methyl salicylate + Menthol", "", "patch", "សាឡុនប៉ាស", "PAIN", "Hasan", 0.25, (("box", 10, 2.30),), 7),
    ("OMEP40", "Omez 40", "Omeprazole", "40 mg", C, "អូមេប្រាហ្សូល ៤០", "GI", "Domesco", 0.20, (("strip", 10, 1.90),), 3),
    ("PANTO40", "Pantoloc", "Pantoprazole", "40 mg", T, "ប៉ង់តូប្រាហ្សូល", "GI", "Stada", 0.35, (("strip", 7, 2.30),), 3),
    ("ORSKIDS", "Oresol kids", "Oral rehydration salts", "5.1 g", "sachet", "អូរ៉េសូល កុមារ", "GI", "Cambodia Pharma", 0.20, (("box", 20, 3.60),), 5),
    ("LACTU", "Duphalac", "Lactulose", "200 ml", "syrup", "ឌូហ្វាឡាក់", "GI", "Stada", 5.50, (), 2),
    ("PROBIO", "Enterogermina", "Bacillus clausii", "5 ml", "vial", "អង់តេរ៉ូហ្សែមីណា", "GI", "Sanofi", 0.60, (("box", 10, 5.80),), 4),
    ("CETISYR", "Zyrtec syrup", "Cetirizine", "5 mg/5 ml", "syrup", "សេទីរីហ្ស៊ីន ទឹកស៊ីរ៉ូ", "RESP", "GSK", 4.20, (), 3),
    ("NASAL", "Otrivin", "Xylometazoline", "0.1% 10 ml", "nasal spray", "អូទ្រីវីន", "RESP", "Novartis", 3.80, (), 4),
    ("VICKS", "Vicks VapoRub", "Camphor + Menthol + Eucalyptus", "25 g", "ointment", "វីក", "RESP", "Reckitt", 2.50, (), 6),
    ("HALLS", "Halls", "Menthol", "", "lozenge", "ហលស៍", "RESP", "Hasan", 0.05, (("strip", 9, 0.45),), 6),
    ("AMBROSYR", "Mucosolvan syrup", "Ambroxol", "15 mg/5 ml", "syrup", "អាំប្រុកសុល ទឹកស៊ីរ៉ូ", "RESP", "Sanofi", 3.20, (), 4),
    ("VITCEFF", "Redoxon", "Ascorbic acid", "1000 mg", "effervescent", "រេដុកសុន", "VIT", "Bayer", 0.40, (("tube", 10, 3.80),), 5),
    ("VITD1000", "Vitamin D3", "Cholecalciferol", "1000 IU", C, "វីតាមីន D3", "VIT", "Mega We Care", 0.10, (("bottle", 60, 5.50),), 3),
    ("MAGB6", "Magne B6", "Magnesium + Vitamin B6", "", T, "ម៉ាញេ B6", "VIT", "Sanofi", 0.15, (("strip", 10, 1.40),), 3),
    ("KIDVIT", "Kid vitamins syrup", "Multivitamins", "120 ml", "syrup", "វីតាមីនកុមារ", "VIT", "Unilab", 3.00, (), 4),
    ("GINSENG", "Ginseng capsules", "Panax ginseng", "500 mg", C, "តិញ្ញាណ", "VIT", "Hasan", 0.25, (("bottle", 30, 7.00),), 2),
    ("SUNSCR", "Sunscreen SPF50", "Zinc oxide + Octinoxate", "50 ml", "lotion", "ក្រែមការពារកំដៅថ្ងៃ", "SKIN", "Mega We Care", 6.00, (), 3),
    ("MOIST", "Moisturising cream", "Urea", "10% 50 g", "cream", "ក្រែមសំណើម", "SKIN", "Stada", 3.20, (), 2),
    ("ACNE", "Acne gel", "Benzoyl peroxide", "5% 15 g", "gel", "ជែលមុន", "SKIN", "Stada", 3.80, (), 3),
    ("PERMETH", "Permethrin cream", "Permethrin", "5% 30 g", "cream", "ប៉ឺមេទ្រីន", "SKIN", "Domesco", 3.00, (), 1),
    ("MIC", "Daktarin", "Miconazole", "2% 15 g", "cream", "មីកូណាហ្សូល", "SKIN", "Stada", 2.60, (), 3),
    ("EYEDROP", "Visine", "Tetrahydrozoline", "0.05% 15 ml", "eye drops", "វីស៊ីន", "EYE", "Hasan", 3.20, (), 3),
    ("EARDROP", "Ear drops", "Chlorobutanol + Paradichlorobenzene", "10 ml", "ear drops", "ថ្នាំដាក់ត្រចៀក", "EYE", "Domesco", 2.00, (), 2),
    ("MOUTHW", "Listerine", "Mouthwash", "250 ml", "solution", "ទឹកខ្ពុរមាត់", "FIRST", "Reckitt", 3.50, (), 4),
    ("GLOVES", "Examination gloves", "Latex gloves", "M", "glove", "ស្រោមដៃ", "FIRST", "Mega We Care", 0.10, (("box", 100, 7.50),), 3),
    ("H2O2", "Hydrogen peroxide", "Hydrogen peroxide", "3% 100 ml", "solution", "អ៊ីដ្រូសែន ពែរ៉ុកស៊ីត", "FIRST", "Cambodia Pharma", 0.90, (), 3),
    ("BURN", "Burn gel", "Aloe vera + Lidocaine", "25 g", "gel", "ជែលរលាក", "FIRST", "Mega We Care", 3.50, (), 2),
    ("ICEPACK", "Cold pack", "Instant cold pack", "", "pack", "ថង់ត្រជាក់", "FIRST", "Mega We Care", 1.50, (), 1),
    ("WATERT", "Water purification tablets", "Sodium dichloroisocyanurate", "67 mg", T, "ថ្នាំចម្រោះទឹក", "FIRST", "Cambodia Pharma", 0.05, (("strip", 10, 0.45),), 1),
    ("REPEL", "Mosquito repellent", "DEET", "15% 60 ml", "lotion", "ថ្នាំការពារមូស", "FIRST", "Hasan", 2.80, (), 5),
    ("CONDOM", "Condoms", "Latex condoms", "", "piece", "ស្រោមអនាម័យ", "WOMEN", "Reckitt", 0.30, (("box", 3, 0.90), ("box12", 12, 3.30)), 4),
    ("PADS", "Sanitary pads", "Sanitary pads", "", "pack", "សំឡីអនាម័យ", "WOMEN", "Mega We Care", 1.50, (), 4),
    ("FERROSYR", "Iron syrup", "Ferrous sulfate", "100 ml", "syrup", "ជាតិដែក ទឹកស៊ីរ៉ូ", "VIT", "Cambodia Pharma", 2.40, (), 2),
    ("CALCSYR", "Calcium syrup", "Calcium + Vitamin D", "120 ml", "syrup", "កាល់ស្យូម ទឹកស៊ីរ៉ូ", "VIT", "Unilab", 3.40, (), 2),
    ("GLUCO", "Glucose powder", "Dextrose", "75 g", "powder", "ម្សៅស្ករ", "GI", "Cambodia Pharma", 0.90, (), 3),
    ("ANTISEP", "Dettol", "Chloroxylenol", "4.8% 100 ml", "solution", "ដេតុល", "FIRST", "Reckitt", 2.20, (), 4),
    ("NEBUL", "Saline nasal drops", "Sodium chloride", "0.9% 15 ml", "nasal drops", "ទឹកអំបិលដាក់ច្រមុះ", "RESP", "Cambodia Pharma", 1.20, (), 3),
    ("THROAT", "Throat spray", "Benzydamine", "30 ml", "spray", "ថ្នាំបាញ់បំពង់ក", "RESP", "Stada", 4.80, (), 2),
    ("ELECTRO", "Electrolyte drink", "Electrolytes", "500 ml", "bottle", "ភេសជ្ជៈអេឡិចត្រូលីត", "GI", "Hasan", 0.80, (("pack", 6, 4.50),), 4),
    ("MULTIKID", "Gummy vitamins", "Multivitamins", "", "gummy", "វីតាមីនស្ករកៅស៊ូ", "VIT", "Mega We Care", 0.12, (("bottle", 60, 6.80),), 2),
    ("WARTS", "Wart remover", "Salicylic acid", "17% 10 ml", "solution", "ថ្នាំព្យាបាលឬស", "SKIN", "Stada", 4.00, (), 1),
    ("ARTSUN", "Artesunate", "Artesunate", "50 mg", T, "អាតេស៊ូណាត", "PARA", "Cambodia Pharma", 0.30, (("box", 12, 3.40),), 1),
    ("PRAZI", "Biltricide", "Praziquantel", "600 mg", T, "ប្រាហ្ស៊ីក្វង់តែល", "PARA", "Bayer", 0.90, (), 1),
    ("NIFED", "Adalat", "Nifedipine", "10 mg", C, "នីហ្វេឌីពីន", "HEART", "Bayer", 0.15, (("strip", 10, 1.40),), 1),
    ("ENAL10", "Renitec", "Enalapril", "10 mg", T, "អេណាឡាព្រីល", "HEART", "Stada", 0.12, (("strip", 10, 1.10),), 2),
    ("GLIB5", "Daonil", "Glibenclamide", "5 mg", T, "ហ្គ្លីបេនក្លាមីដ", "DIAB", "Sanofi", 0.05, (("strip", 10, 0.45),), 2),
    ("GLUCOM", "Glucometer strips", "Blood glucose test strips", "", "strip", "បន្ទះតេស្តជាតិស្ករ", "DIAB", "Abbott", 0.40, (("box", 25, 9.50),), 2),
    ("BPMON", "Blood pressure monitor", "BP monitor", "", "device", "ឧបករណ៍វាស់សម្ពាធឈាម", "HEART", "Mega We Care", 28.00, (), 1),
    ("SYRINGE", "Syringe 5 ml", "Syringe", "5 ml", "piece", "ស៊ីរ៉ាំង", "FIRST", "Cambodia Pharma", 0.10, (("box", 100, 8.00),), 1),
    ("NEEDLE", "Insulin syringes", "Insulin syringe", "1 ml", "piece", "ស៊ីរ៉ាំងអាំងស៊ុយលីន", "DIAB", "Cambodia Pharma", 0.15, (("box", 100, 12.00),), 1),
    ("COLDPATCH", "Fever cooling patch", "Cooling gel patch", "", "patch", "បន្ទះបញ្ចុះកំដៅ", "PAIN", "Hasan", 0.40, (("box", 6, 2.20),), 4),
    ("MUSCLE", "Muscle rub", "Methyl salicylate", "30 g", "cream", "ក្រែមលាបសាច់ដុំ", "PAIN", "Hasan", 2.40, (), 3),
    ("NAUSEA", "Ginger tablets", "Ginger extract", "250 mg", T, "ខ្ញីគ្រាប់", "GI", "Hasan", 0.08, (("strip", 10, 0.75),), 2),
    ("SLEEP", "Melatonin", "Melatonin", "3 mg", T, "មេឡាតូនីន", "NERVE", "Mega We Care", 0.20, (("bottle", 30, 5.80),), 1),
    ("HEMOR", "Hemorrhoid cream", "Lidocaine + Hydrocortisone", "25 g", "cream", "ក្រែមឫសដូងបាត", "SKIN", "Stada", 4.20, (), 1),
    ("LICE", "Lice shampoo", "Permethrin", "1% 60 ml", "shampoo", "សាប៊ូកក់ចៃ", "SKIN", "Domesco", 3.00, (), 1),
]

# Extra Rx-only (prescription) and controlled lines in EXTRA: none; Rx flags are on MEDICINES rows.

HAMPERS = [  # sku, name, Khmer, price, [(sku, qty_base)]
    ("KIT-FIRSTAID", "First-aid kit", "ប្រអប់សង្គ្រោះបឋម", 9.90,
     [("PLASTER", 20), ("GAUZE", 2), ("BANDAGE", 1), ("BETADINE", 1), ("ALCOHOL", 1), ("COTTON", 1)]),
    ("KIT-COLDFLU", "Cold & flu pack", "កញ្ចប់ផ្តាសាយ", 4.90,
     [("DECOL", 8), ("VITC500", 10), ("STREP", 8), ("ORS", 2)]),
]

# --- places and people ------------------------------------------------------------------------------------
BRANCHES = [  # code, name_en, name_km, address, phone, header
    ("PP1", "Toul Kork", "ទួលគោក", "St. 289, Toul Kork, Phnom Penh", "023 880 101",
     "Pharmacy Toul Kork · St. 289 · Tel 023 880 101"),
    ("PP2", "BKK1", "បឹងកេងកង ១", "St. 278, BKK1, Phnom Penh", "023 880 202",
     "Pharmacy BKK1 · St. 278 · Tel 023 880 202"),
    ("SR1", "Siem Reap", "សៀមរាប", "Sivatha Blvd, Siem Reap", "063 760 303",
     "Pharmacy Siem Reap · Sivatha Blvd · Tel 063 760 303"),
]

# (Khmer family, English family) and given names (Khmer, English)
FAMILY = [("សុខ", "Sok"), ("ចាន់", "Chan"), ("ហេង", "Heng"), ("លី", "Ly"), ("ស៊ុន", "Sun"), ("គឹម", "Kim"),
          ("ម៉ៅ", "Mao"), ("ឈឹម", "Chhim"), ("ពេជ្រ", "Pich"), ("ទេព", "Tep"), ("អ៊ុក", "Ouk"), ("ស៊ាង", "Seang"),
          ("ណុប", "Nop"), ("វង្ស", "Vong"), ("ខៀវ", "Khiev"), ("យិន", "Yin")]
GIVEN = [("ដារ៉ា", "Dara"), ("សុភា", "Sophea"), ("វិចិត្រ", "Vichet"), ("ស្រីនាង", "Sreyneang"), ("រតនា", "Ratana"),
         ("ពិសិដ្ឋ", "Piseth"), ("សុជាតា", "Socheata"), ("បុប្ផា", "Bopha"), ("វណ្ណា", "Vanna"), ("ចន្ទ្រា", "Chantrea"),
         ("សំណាង", "Samnang"), ("ធារី", "Theary"), ("រស្មី", "Reaksmey"), ("មករា", "Makara"), ("លីដា", "Lida"),
         ("សុវណ្ណ", "Sovann"), ("ចិន្តា", "Chenda"), ("បូរ៉ា", "Bora"), ("នីតា", "Nita"), ("កញ្ញា", "Kanha")]

SUPPLIER_GROUPS = [("Local distributors", "អ្នកចែកចាយក្នុងស្រុក"), ("Importers", "អ្នកនាំចូល")]
SUPPLIERS = [  # code, name, Khmer, phone, terms, group
    ("DKSH", "DKSH Cambodia", "ឌីខេអេសអេច កម្ពុជា", "023 990 111", 30, 1),
    ("ZUEL", "Zuellig Pharma Cambodia", "ហ្ស៊ូលីក ហ្វាម៉ា", "023 990 222", 45, 1),
    ("MEGA", "Mega Lifesciences Cambodia", "មេហ្គា កម្ពុជា", "023 990 333", 30, 0),
    ("UNIP", "Unipharma Trading", "យូនីហ្វាម៉ា", "023 990 444", 15, 0),
    ("ABC", "ABC Pharma Distribution", "អេប៊ីស៊ី ហ្វាម៉ា", "023 990 555", 30, 0),
    ("KHMED", "Khmer Medical Supply", "ផ្គត់ផ្គង់វេជ្ជសាស្ត្រខ្មែរ", "023 990 666", 7, 0),
]

CUSTOMER_GROUPS = [("Retail", "លក់រាយ", "0"), ("Clinic", "គ្លីនិក", "5"), ("Wholesale", "លក់ដុំ", "8")]
CLINICS = ["Sen Sok Clinic", "Royal Care Clinic", "Angkor Family Clinic", "Daun Penh Medical", "Mekong Health"]

CONDITIONS = ["Hypertension", "Type 2 diabetes", "Asthma", "High cholesterol", "Gastritis", "Arthritis", "", "", ""]
ALLERGIES = [("class", "penicillins"), ("ingredient", "aspirin"), ("class", "sulfonamides"), ("ingredient", "ibuprofen")]
SPECIALTIES = ["General practice", "Internal medicine", "Paediatrics", "Cardiology", "Endocrinology", "Dermatology"]
