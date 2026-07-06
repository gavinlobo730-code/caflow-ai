-- Migration 175 — HSN/SAC master modernization (Sales-Invoice Batch 5)
--
-- Goal: replace the limited ~39-row curated seed (migration 036) with a
-- comprehensive OFFICIAL master while preserving backward compatibility.
--
-- Provenance / licensing / update strategy
-- ----------------------------------------
-- Source data is the CBIC HSN (Customs Tariff Act, First Schedule) chapter set
-- and the GST SAC scheme (Annexure to Notification 11/2017-Central Tax (Rate),
-- itself derived from the UN CPC). Both are Government of India publications in
-- the public domain — no third-party licence is required to embed them.
--
-- This seed loads the OFFICIAL BACKBONE that makes every code searchable by
-- prefix: all HSN 2-digit chapters (01–98, 77 reserved) and all SAC 4-digit
-- service groups (9954–9997), plus the commonly-invoiced 6-digit SAC leaves a CA
-- practice uses. Chapter- and group-level rows carry gst_rate_pct = NULL on
-- purpose: a chapter or a 4-digit group spans several GST rates, so any single
-- rate would be wrong. The rate is only a UI PRE-FILL HINT (CGST Rule 46(g)) and
-- is never used in tax or journal math, so NULL is the correct, honest default;
-- the CA always sets the rate. The full 8-digit HSN leaf catalogue (~12k rows)
-- is a large dataset best refreshed out-of-band via a versioned data pipeline
-- into this same table and schema; `source` + `version` below let a later load
-- bump a code's row in place without a schema change.
--
-- Backward compatibility: sales-invoice lines store hsn_sac as FREE TEXT (no FK
-- to hsn_master) and nothing joins hsn_master except the lookup search endpoint,
-- so expanding or correcting the master can never alter or break an existing
-- invoice, GSTR-1 return or PDF — it only widens/sharpens what the picker finds.
--
-- Data correction (Bug Fix Rule): several 6-digit SAC codes in the original 036
-- seed were mapped to the wrong official title (e.g. 998212 was "Financial
-- auditing" but is officially a legal-services code; auditing is 998221). Because
-- the master feeds only the lookup, this upsert (ON CONFLICT DO UPDATE) safely
-- corrects those legacy code→title mis-mappings to the official CBIC SAC scheme.
-- Legacy goods codes not listed here (e.g. 8471, 7108) are left untouched.

-- 1) Provenance / versioning columns (additive, nullable — safe on re-run).
ALTER TABLE public.hsn_master ADD COLUMN IF NOT EXISTS source     TEXT;
ALTER TABLE public.hsn_master ADD COLUMN IF NOT EXISTS version    TEXT;
ALTER TABLE public.hsn_master ADD COLUMN IF NOT EXISTS keywords   TEXT;
ALTER TABLE public.hsn_master ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill provenance for the original curated seed (migration 036) before the
-- official upsert overwrites the codes it supersedes.
UPDATE public.hsn_master
   SET source = 'cbic_curated_2017'
 WHERE source IS NULL;

-- A (hsn_type, hsn_code) index keeps the type-filtered prefix lookups quick as
-- the master grows.
CREATE INDEX IF NOT EXISTS idx_hsn_master_type_code
  ON public.hsn_master (hsn_type, hsn_code);

-- 2) Comprehensive official seed / upsert.
INSERT INTO public.hsn_master (hsn_code, description, gst_rate_pct, hsn_type, uqc, source, version, keywords) VALUES
-- HSN 2-digit chapters (01–98, chapter 77 reserved/omitted). Rates NULL (a chapter spans multiple GST rates).
('01','Live animals', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'animals livestock cattle'),
('02','Meat and edible meat offal', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'meat mutton chicken pork'),
('03','Fish and crustaceans, molluscs and aquatic invertebrates', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'fish seafood prawn crab'),
('04','Dairy produce; eggs; honey; edible animal products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'milk dairy egg honey cheese'),
('05','Products of animal origin, not elsewhere specified', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'animal origin bones'),
('06','Live trees and plants; bulbs, roots; cut flowers', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'plants flowers nursery'),
('07','Edible vegetables and certain roots and tubers', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'vegetables potato onion'),
('08','Edible fruit and nuts; peel of citrus fruit or melons', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'fruit nuts dryfruit'),
('09','Coffee, tea, mate and spices', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'coffee tea spices masala'),
('10','Cereals', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'rice wheat grain cereal'),
('11','Products of the milling industry; malt; starches', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'flour atta maida starch'),
('12','Oil seeds and oleaginous fruits; seeds, grains', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'oilseed groundnut soybean'),
('13','Lac; gums, resins and vegetable saps and extracts', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'gum resin lac'),
('14','Vegetable plaiting materials; vegetable products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'bamboo cane vegetable'),
('15','Animal or vegetable fats and oils and cleavage products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'oil ghee fat vanaspati'),
('16','Preparations of meat, fish, crustaceans or molluscs', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'meat fish preparations'),
('17','Sugars and sugar confectionery', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'sugar jaggery sweets candy'),
('18','Cocoa and cocoa preparations', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'cocoa chocolate'),
('19','Preparations of cereals, flour, starch or milk; pastry', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'biscuit bread pasta noodles'),
('20','Preparations of vegetables, fruit, nuts or plant parts', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'jam pickle juice sauce'),
('21','Miscellaneous edible preparations', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'sauces soup namkeen'),
('22','Beverages, spirits and vinegar', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'water beverage drink liquor'),
('23','Residues from food industries; prepared animal fodder', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'cattle feed fodder oilcake'),
('24','Tobacco and manufactured tobacco substitutes', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'tobacco cigarette bidi'),
('25','Salt; sulphur; earths and stone; lime and cement', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'salt cement stone marble'),
('26','Ores, slag and ash', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'ore metal slag ash'),
('27','Mineral fuels, mineral oils and distillation products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'petrol diesel coal fuel oil'),
('28','Inorganic chemicals; compounds of precious metals', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'inorganic chemical acid'),
('29','Organic chemicals', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'organic chemical'),
('30','Pharmaceutical products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'medicine pharma drug tablet'),
('31','Fertilisers', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'fertiliser urea manure'),
('32','Tanning or dyeing extracts; dyes, pigments, paints, inks', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'paint dye ink pigment'),
('33','Essential oils and resinoids; perfumery and cosmetics', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'perfume cosmetic soap beauty'),
('34','Soap, waxes, polishing preparations and candles', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'soap detergent wax candle'),
('35','Albuminoidal substances; modified starches; glues; enzymes', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'glue gelatin enzyme'),
('36','Explosives; pyrotechnics; matches; pyrophoric alloys', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'explosive matches firework'),
('37','Photographic or cinematographic goods', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'photo film camera'),
('38','Miscellaneous chemical products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'chemical products'),
('39','Plastics and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'plastic polymer pvc'),
('40','Rubber and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'rubber tyre tube'),
('41','Raw hides and skins (other than furskins) and leather', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'leather hide skin'),
('42','Articles of leather; saddlery; travel goods and handbags', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'leather bag wallet belt'),
('43','Furskins and artificial fur; manufactures thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'fur furskin'),
('44','Wood and articles of wood; wood charcoal', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'wood timber plywood charcoal'),
('45','Cork and articles of cork', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'cork'),
('46','Manufactures of straw, esparto; basketware and wickerwork', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'straw basket wickerwork'),
('47','Pulp of wood; recovered paper and paperboard waste', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'pulp waste paper'),
('48','Paper and paperboard; articles of paper pulp', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'paper paperboard carton'),
('49','Printed books, newspapers, pictures and printed products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'book newspaper printed'),
('50','Silk', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'silk yarn'),
('51','Wool, fine or coarse animal hair; horsehair yarn and fabric', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'wool woollen yarn'),
('52','Cotton', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'cotton yarn fabric'),
('53','Other vegetable textile fibres; paper yarn and fabric', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'jute flax hemp fibre'),
('54','Man-made filaments; strip of man-made textile materials', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'synthetic filament yarn'),
('55','Man-made staple fibres', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'polyester staple fibre'),
('56','Wadding, felt and nonwovens; twine, cordage and ropes', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'rope twine felt nonwoven'),
('57','Carpets and other textile floor coverings', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'carpet rug mat floor'),
('58','Special woven fabrics; tufted textiles; lace; tapestries', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'lace embroidery fabric'),
('59','Impregnated, coated or laminated textile fabrics', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'coated fabric'),
('60','Knitted or crocheted fabrics', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'knitted crochet fabric'),
('61','Articles of apparel and clothing accessories, knitted', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'garment clothing apparel knit'),
('62','Articles of apparel and clothing accessories, not knitted', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'garment clothing apparel'),
('63','Other made up textile articles; sets; worn clothing; rags', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'bedsheet towel textile'),
('64','Footwear, gaiters and the like; parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'footwear shoe chappal'),
('65','Headgear and parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'hat cap headgear'),
('66','Umbrellas, walking sticks, whips and parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'umbrella walking stick'),
('67','Prepared feathers and down; artificial flowers; human hair', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'feather wig artificial flower'),
('68','Articles of stone, plaster, cement, asbestos and mica', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'stone marble granite cement'),
('69','Ceramic products', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'ceramic tile pottery brick'),
('70','Glass and glassware', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'glass glassware mirror'),
('71','Pearls, precious stones and metals; imitation jewellery', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'gold silver jewellery diamond'),
('72','Iron and steel', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'iron steel tmt'),
('73','Articles of iron or steel', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'steel articles pipe'),
('74','Copper and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'copper wire'),
('75','Nickel and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'nickel'),
('76','Aluminium and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'aluminium foil'),
('78','Lead and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'lead'),
('79','Zinc and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'zinc'),
('80','Tin and articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'tin'),
('81','Other base metals; cermets; articles thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'base metal tungsten'),
('82','Tools, implements, cutlery, spoons and forks of base metal', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'tools cutlery knife hardware'),
('83','Miscellaneous articles of base metal', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'lock hinge metal fittings'),
('84','Nuclear reactors, boilers, machinery and mechanical appliances', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'machinery machine mechanical'),
('85','Electrical machinery and equipment and parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'electrical electronics'),
('86','Railway or tramway locomotives, rolling stock and parts', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'railway train locomotive'),
('87','Vehicles other than railway or tramway rolling stock', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'car vehicle motorcycle truck'),
('88','Aircraft, spacecraft and parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'aircraft aeroplane'),
('89','Ships, boats and floating structures', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'ship boat vessel'),
('90','Optical, photographic, medical or surgical instruments', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'optical medical instrument'),
('91','Clocks and watches and parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'watch clock'),
('92','Musical instruments; parts and accessories thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'musical instrument guitar'),
('93','Arms and ammunition; parts and accessories thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'arms weapon ammunition'),
('94','Furniture; bedding and mattresses; lamps and lighting', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'furniture chair table lamp'),
('95','Toys, games and sports requisites; parts thereof', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'toys games sports'),
('96','Miscellaneous manufactured articles', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'pen brush comb button'),
('97','Works of art, collectors pieces and antiques', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'art painting antique'),
('98','Project imports, laboratory chemicals and personal imports', NULL, 'goods', 'NOS', 'cbic_tariff_2025', '2025-26', 'project imports baggage'),
-- SAC 4-digit service groups (Annexure to Notification 11/2017-CTR). Rates NULL (a group spans multiple rates).
('9954','Construction services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'construction building works contract'),
('9961','Services in wholesale trade', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'wholesale trade distribution'),
('9962','Services in retail trade', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'retail trade shop'),
('9963','Accommodation, food and beverage services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'hotel restaurant catering food'),
('9964','Passenger transport services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'passenger travel transport'),
('9965','Goods transport services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'freight goods transport logistics'),
('9966','Rental services of transport vehicles with operators', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'vehicle rental hire with driver'),
('9967','Supporting services in transport', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'cargo handling warehousing transport'),
('9968','Postal and courier services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'postal courier parcel delivery'),
('9969','Electricity, gas, water and other distribution services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'electricity gas water distribution'),
('9971','Financial and related services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'finance banking loan insurance'),
('9972','Real estate services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'real estate property rent lease'),
('9973','Leasing or rental services without operator', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'leasing rental hire equipment'),
('9981','Research and development services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'research development rnd'),
('9982','Legal and accounting services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'legal accounting audit tax lawyer ca'),
('9983','Other professional, technical and business services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'consulting engineering it software advertising'),
('9984','Telecommunications, broadcasting and information supply services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'telecom internet broadcasting'),
('9985','Support services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'support manpower security housekeeping'),
('9986','Support services to agriculture, hunting, forestry, fishing', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'agriculture farming support'),
('9987','Maintenance, repair and installation (except construction) services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'maintenance repair installation amc'),
('9988','Manufacturing services on physical inputs owned by others', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'job work manufacturing'),
('9989','Other manufacturing, publishing, printing and reproduction services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'printing publishing job work'),
('9991','Public administration and compulsory social security services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'public administration government'),
('9992','Education services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'education school college training'),
('9993','Human health and social care services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'health medical hospital care'),
('9994','Sewage, waste collection, treatment and disposal services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'sewage waste sanitation garbage'),
('9995','Services of membership organisations', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'membership association club'),
('9996','Recreational, cultural and sporting services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'entertainment recreation sports culture'),
('9997','Other services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'other services miscellaneous'),
-- Commonly-invoiced 6-digit SAC codes. 18.00 = standard rate for professional/IT/legal/accounting/consulting services.
('998211','Legal advisory and representation services - criminal law', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'legal lawyer advocate criminal'),
('998212','Legal advisory and representation - other fields of law', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'legal lawyer advocate civil'),
('998213','Legal documentation and certification - intellectual property', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'legal patent copyright trademark ipr'),
('998215','Arbitration and conciliation services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'arbitration mediation dispute'),
('998216','Other legal services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'legal notary'),
('998221','Financial auditing services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'audit statutory auditor ca'),
('998222','Accounting and bookkeeping services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'accounting bookkeeping ledger'),
('998223','Payroll services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'payroll salary'),
('998231','Corporate tax consulting and preparation services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'tax consulting corporate return filing'),
('998232','Individual tax preparation and planning services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'income tax itr filing individual'),
('998311','Management consulting and management services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'management consulting advisory'),
('998312','Business consulting services including public relations', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'business consulting pr'),
('998313','Information technology consulting and support services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'it consulting support software'),
('998314','Information technology design and development services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'software development it coding'),
('998315','Hosting and IT infrastructure provisioning services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'hosting cloud server web'),
('998316','IT infrastructure and network management services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'network management it infrastructure'),
('998319','Other information technology services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'it services software'),
('998321','Architectural advisory services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'architect design advisory'),
('998322','Architectural services for residential building projects', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'architect residential building'),
('998323','Architectural services for non-residential building projects', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'architect commercial building'),
('998331','Engineering advisory services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'engineering advisory consultancy'),
('998332','Engineering services for building projects', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'engineering building structural'),
('998333','Engineering services for industrial and manufacturing projects', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'engineering industrial manufacturing'),
('998346','Technical testing and analysis services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'testing laboratory inspection analysis'),
('998361','Advertising services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'advertising ads branding campaign'),
('998363','Sale of advertising space in print media on commission', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'advertising print media space'),
('998371','Market research services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'market research survey polling'),
('997152','Brokerage and related securities and commodities services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'brokerage securities commodities broker'),
('997156','Financial consultancy services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'financial consultancy advisory'),
('997157','Foreign exchange services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'forex foreign exchange currency'),
-- 997211: residential renting for use as residence is GST-exempt; rate depends on use/registration → NULL.
('997211','Rental services of own or leased residential property', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'rent residential house lease'),
('997212','Rental services of own or leased non-residential property', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'rent commercial office shop lease'),
('997221','Property management services on a fee or contract basis', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'property management real estate'),
('997224','Real estate appraisal services on fee or commission basis', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'property valuation appraisal'),
('997331','Licensing services for the right to use computer software', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'software license saas subscription'),
('998413','Mobile telecommunications services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'mobile telecom sim call data'),
('998113','Research and experimental development in engineering', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'research development engineering rnd'),
('999293','Commercial training and coaching services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'coaching training tuition classes'),
('999294','Other education and training services', 18.00, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'education training skill'),
-- 999210: recognised pre-primary education is GST-exempt, not 18% → NULL.
('999210','Pre-primary education services', NULL, 'services', 'OTH', 'cbic_sac_2025', '2025-26', 'preschool education play school')
ON CONFLICT (hsn_code) DO UPDATE SET
  description  = EXCLUDED.description,
  gst_rate_pct = EXCLUDED.gst_rate_pct,
  hsn_type     = EXCLUDED.hsn_type,
  uqc          = EXCLUDED.uqc,
  source       = EXCLUDED.source,
  version      = EXCLUDED.version,
  keywords     = EXCLUDED.keywords,
  updated_at   = now();
