"""Canonical country/region reference data for discovery region matching.

Single source of truth for region resolution (aliases), region "fit" signals
(ccTLD, dialing code, cities), translation/search languages, and foreign-country
detection (names, demonyms, ambiguity). `discovery.py` derives all of its
`_REGION_*` / `_COUNTRY_*` lookup dicts from `COUNTRIES` at import time, so this
file is the only place to add or widen a country.

Per-country fields (all optional except `aliases`):
  aliases   - lower-case freeform names that resolve to this canonical key.
  demonyms  - lower-case adjectives ("british", "cameroonian"); matched on \\b
              (also accept the "<dem>-based" form) for location detection.
  cctld     - country-code TLD without the dot ("tr"). Omit for none.
  phone     - E.164 calling code with the leading "+". Codes shared across
              countries (+1 NANP, +7) resolve to the first listed owner.
  cities    - a few major cities (lower-case) used as address/HQ anchors.
  langs     - business-web languages to ALSO search/translate into (ISO 639-1
              codes), most-productive first. OMITTED where English is the de-facto
              business web language (translation no-ops there). Multilingual markets
              list several — morocco ["fr","ar"], switzerland ["de","fr","it"],
              belgium ["nl","fr"] — and EACH is searched. Foreign companies that
              merely share a language (a French firm surfacing in a French Morocco
              search) are dropped downstream by region_fit's foreign-country conflict
              detection (ccTLD / phone / stated-address country), so a wider language
              net adds recall without letting other countries in.
  ambiguous - True when the country NAME doubles as a common word / brand /
              personal name / US place (turkey, china, georgia, jordan, chad...).
              Such names are excluded from domain-label matching and never
              trigger a foreign-country *reject* (used for display only), so a
              `jordanlumber.com` or "Atlanta, Georgia, USA" is not misread.
"""

from __future__ import annotations


# ccTLDs widely repurposed as generic / vanity domains. They must NOT count as a
# country signal (positive or conflict) — else e.g. acme.io would be read as
# "British Indian Ocean Territory" and wrongly rejected.
GENERIC_TLDS: set[str] = {
    "co", "io", "ai", "tv", "me", "fm", "ly", "gg", "to",
    "cc", "ws", "am", "sh", "ms", "mu", "vc", "la", "is",
}


COUNTRIES: dict[str, dict] = {
    # ---- South / Central Asia -------------------------------------------------
    "bangladesh": {"aliases": ["bangladesh"], "demonyms": ["bangladeshi"],
                   "cctld": "bd", "phone": "+880", "langs": ["bn"],
                   "cities": ["dhaka", "chattogram", "chittagong", "khulna", "sylhet", "rajshahi"]},
    "india": {"aliases": ["india"], "demonyms": ["indian"], "cctld": "in", "phone": "+91",
              "cities": ["mumbai", "delhi", "new delhi", "bengaluru", "bangalore", "hyderabad", "chennai", "pune", "kolkata", "ahmedabad"]},
    "pakistan": {"aliases": ["pakistan"], "demonyms": ["pakistani"], "cctld": "pk", "phone": "+92",
                 "cities": ["karachi", "lahore", "islamabad", "faisalabad", "rawalpindi"]},
    "sri lanka": {"aliases": ["sri lanka"], "demonyms": ["sri lankan"], "cctld": "lk", "phone": "+94",
                  "cities": ["colombo", "kandy"]},
    "nepal": {"aliases": ["nepal"], "demonyms": ["nepali", "nepalese"], "cctld": "np", "phone": "+977", "langs": ["ne"],
              "cities": ["kathmandu"]},
    "afghanistan": {"aliases": ["afghanistan"], "demonyms": ["afghan"], "cctld": "af", "phone": "+93", "langs": ["fa", "ps"],
                    "cities": ["kabul"]},
    "kazakhstan": {"aliases": ["kazakhstan"], "demonyms": ["kazakh"], "cctld": "kz", "phone": "+7", "langs": ["ru", "kk"],
                   "cities": ["almaty", "astana", "nur-sultan"]},
    "uzbekistan": {"aliases": ["uzbekistan"], "demonyms": ["uzbek"], "cctld": "uz", "phone": "+998", "langs": ["ru", "uz"],
                   "cities": ["tashkent"]},

    # ---- East / Southeast Asia ------------------------------------------------
    "china": {"aliases": ["china", "prc"], "demonyms": ["chinese"], "cctld": "cn", "phone": "+86", "langs": ["zh"],
              "cities": ["beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "chengdu"], "ambiguous": True},
    "japan": {"aliases": ["japan"], "demonyms": ["japanese"], "cctld": "jp", "phone": "+81", "langs": ["ja"],
              "cities": ["tokyo", "osaka", "yokohama", "nagoya", "kyoto"]},
    "south korea": {"aliases": ["south korea", "korea", "republic of korea"], "demonyms": ["korean"],
                    "cctld": "kr", "phone": "+82", "langs": ["ko"], "cities": ["seoul", "busan", "incheon"]},
    "taiwan": {"aliases": ["taiwan"], "demonyms": ["taiwanese"], "cctld": "tw", "phone": "+886", "langs": ["zh"],
               "cities": ["taipei", "kaohsiung"]},
    "hong kong": {"aliases": ["hong kong"], "demonyms": ["hong konger"], "cctld": "hk", "phone": "+852", "langs": ["zh"],
                  "cities": ["hong kong", "kowloon"]},
    "indonesia": {"aliases": ["indonesia"], "demonyms": ["indonesian"], "cctld": "id", "phone": "+62", "langs": ["id"],
                  "cities": ["jakarta", "surabaya", "bandung", "medan", "semarang"]},
    "vietnam": {"aliases": ["vietnam", "viet nam"], "demonyms": ["vietnamese"], "cctld": "vn", "phone": "+84", "langs": ["vi"],
                "cities": ["hanoi", "ho chi minh city", "saigon", "da nang"]},
    "thailand": {"aliases": ["thailand"], "demonyms": ["thai"], "cctld": "th", "phone": "+66", "langs": ["th"],
                 "cities": ["bangkok", "chiang mai"]},
    "malaysia": {"aliases": ["malaysia"], "demonyms": ["malaysian"], "cctld": "my", "phone": "+60", "langs": ["ms"],
                 "cities": ["kuala lumpur", "johor bahru", "penang"]},
    "singapore": {"aliases": ["singapore"], "demonyms": ["singaporean"], "cctld": "sg", "phone": "+65",
                  "cities": ["singapore"]},
    "philippines": {"aliases": ["philippines"], "demonyms": ["filipino", "philippine"], "cctld": "ph", "phone": "+63",
                    "cities": ["manila", "quezon city", "cebu", "davao"]},
    "myanmar": {"aliases": ["myanmar", "burma"], "demonyms": ["burmese"], "cctld": "mm", "phone": "+95", "langs": ["my"],
                "cities": ["yangon", "naypyidaw"]},
    "cambodia": {"aliases": ["cambodia"], "demonyms": ["cambodian"], "cctld": "kh", "phone": "+855", "langs": ["km"],
                 "cities": ["phnom penh"]},
    "laos": {"aliases": ["laos"], "demonyms": ["lao", "laotian"], "cctld": "la", "phone": "+856", "langs": ["lo"],
             "cities": ["vientiane"]},
    "mongolia": {"aliases": ["mongolia"], "demonyms": ["mongolian"], "cctld": "mn", "phone": "+976", "langs": ["mn"],
                 "cities": ["ulaanbaatar"]},

    # ---- Middle East ----------------------------------------------------------
    "turkey": {"aliases": ["turkey", "türkiye", "turkiye"], "demonyms": ["turkish"], "cctld": "tr", "phone": "+90", "langs": ["tr"],
               "cities": ["istanbul", "ankara", "izmir", "bursa", "antalya", "adana", "gaziantep", "konya", "kocaeli", "mersin"],
               "ambiguous": True},
    "saudi arabia": {"aliases": ["saudi arabia", "saudi", "ksa"], "demonyms": ["saudi"], "cctld": "sa", "phone": "+966", "langs": ["ar"],
                     "cities": ["riyadh", "jeddah", "dammam", "mecca"]},
    "united arab emirates": {"aliases": ["united arab emirates", "uae"], "demonyms": ["emirati"], "cctld": "ae", "phone": "+971", "langs": ["ar"],
                             "cities": ["dubai", "abu dhabi", "sharjah"]},
    "qatar": {"aliases": ["qatar"], "demonyms": ["qatari"], "cctld": "qa", "phone": "+974", "langs": ["ar"], "cities": ["doha"]},
    "kuwait": {"aliases": ["kuwait"], "demonyms": ["kuwaiti"], "cctld": "kw", "phone": "+965", "langs": ["ar"], "cities": ["kuwait city"]},
    "bahrain": {"aliases": ["bahrain"], "demonyms": ["bahraini"], "cctld": "bh", "phone": "+973", "langs": ["ar"], "cities": ["manama"]},
    "oman": {"aliases": ["oman"], "demonyms": ["omani"], "cctld": "om", "phone": "+968", "langs": ["ar"], "cities": ["muscat"]},
    "israel": {"aliases": ["israel"], "demonyms": ["israeli"], "cctld": "il", "phone": "+972", "langs": ["he"],
               "cities": ["tel aviv", "jerusalem", "haifa"]},
    "jordan": {"aliases": ["jordan"], "demonyms": ["jordanian"], "cctld": "jo", "phone": "+962", "langs": ["ar"],
               "cities": ["amman"], "ambiguous": True},
    "lebanon": {"aliases": ["lebanon"], "demonyms": ["lebanese"], "cctld": "lb", "phone": "+961", "langs": ["ar", "fr"], "cities": ["beirut"]},
    "iraq": {"aliases": ["iraq"], "demonyms": ["iraqi"], "cctld": "iq", "phone": "+964", "langs": ["ar"], "cities": ["baghdad", "basra", "erbil"]},
    "iran": {"aliases": ["iran"], "demonyms": ["iranian"], "cctld": "ir", "phone": "+98", "langs": ["fa"], "cities": ["tehran", "isfahan"]},
    "yemen": {"aliases": ["yemen"], "demonyms": ["yemeni"], "cctld": "ye", "phone": "+967", "langs": ["ar"], "cities": ["sanaa"]},
    "syria": {"aliases": ["syria"], "demonyms": ["syrian"], "cctld": "sy", "phone": "+963", "langs": ["ar"], "cities": ["damascus", "aleppo"]},

    # ---- Africa ---------------------------------------------------------------
    "nigeria": {"aliases": ["nigeria"], "demonyms": ["nigerian"], "cctld": "ng", "phone": "+234",
                "cities": ["lagos", "abuja", "kano", "ibadan"]},
    "kenya": {"aliases": ["kenya"], "demonyms": ["kenyan"], "cctld": "ke", "phone": "+254",
              "cities": ["nairobi", "mombasa"]},
    "south africa": {"aliases": ["south africa"], "demonyms": ["south african"], "cctld": "za", "phone": "+27",
                     "cities": ["johannesburg", "cape town", "durban", "pretoria"]},
    "egypt": {"aliases": ["egypt"], "demonyms": ["egyptian"], "cctld": "eg", "phone": "+20", "langs": ["ar"],
              "cities": ["cairo", "alexandria", "giza"]},
    "morocco": {"aliases": ["morocco"], "demonyms": ["moroccan"], "cctld": "ma", "phone": "+212", "langs": ["fr", "ar"],
                "cities": ["casablanca", "rabat", "marrakech", "tangier"]},
    "ghana": {"aliases": ["ghana"], "demonyms": ["ghanaian"], "cctld": "gh", "phone": "+233",
              "cities": ["accra", "kumasi", "tema"]},
    "cameroon": {"aliases": ["cameroon", "cameroun"], "demonyms": ["cameroonian"], "cctld": "cm", "phone": "+237", "langs": ["fr"],
                 "cities": ["douala", "yaounde", "yaoundé"]},
    "ethiopia": {"aliases": ["ethiopia"], "demonyms": ["ethiopian"], "cctld": "et", "phone": "+251", "langs": ["am"],
                 "cities": ["addis ababa"]},
    "tanzania": {"aliases": ["tanzania"], "demonyms": ["tanzanian"], "cctld": "tz", "phone": "+255", "langs": ["sw"],
                 "cities": ["dar es salaam", "dodoma"]},
    "uganda": {"aliases": ["uganda"], "demonyms": ["ugandan"], "cctld": "ug", "phone": "+256", "cities": ["kampala"]},
    "algeria": {"aliases": ["algeria"], "demonyms": ["algerian"], "cctld": "dz", "phone": "+213", "langs": ["fr", "ar"], "cities": ["algiers", "oran"]},
    "tunisia": {"aliases": ["tunisia"], "demonyms": ["tunisian"], "cctld": "tn", "phone": "+216", "langs": ["fr", "ar"], "cities": ["tunis"]},
    "ivory coast": {"aliases": ["ivory coast", "côte d'ivoire", "cote d'ivoire"], "demonyms": ["ivorian"],
                    "cctld": "ci", "phone": "+225", "langs": ["fr"], "cities": ["abidjan", "yamoussoukro"]},
    "senegal": {"aliases": ["senegal"], "demonyms": ["senegalese"], "cctld": "sn", "phone": "+221", "langs": ["fr"], "cities": ["dakar"]},
    "angola": {"aliases": ["angola"], "demonyms": ["angolan"], "cctld": "ao", "phone": "+244", "langs": ["pt"], "cities": ["luanda"]},
    "zambia": {"aliases": ["zambia"], "demonyms": ["zambian"], "cctld": "zm", "phone": "+260", "cities": ["lusaka"]},
    "zimbabwe": {"aliases": ["zimbabwe"], "demonyms": ["zimbabwean"], "cctld": "zw", "phone": "+263", "cities": ["harare"]},
    "rwanda": {"aliases": ["rwanda"], "demonyms": ["rwandan"], "cctld": "rw", "phone": "+250", "langs": ["fr"], "cities": ["kigali"]},
    "mozambique": {"aliases": ["mozambique"], "demonyms": ["mozambican"], "cctld": "mz", "phone": "+258", "langs": ["pt"], "cities": ["maputo"]},
    "botswana": {"aliases": ["botswana"], "demonyms": ["botswanan"], "cctld": "bw", "phone": "+267", "cities": ["gaborone"]},
    "namibia": {"aliases": ["namibia"], "demonyms": ["namibian"], "cctld": "na", "phone": "+264", "cities": ["windhoek"]},
    "gabon": {"aliases": ["gabon"], "demonyms": ["gabonese"], "cctld": "ga", "phone": "+241", "langs": ["fr"], "cities": ["libreville"]},
    "sudan": {"aliases": ["sudan"], "demonyms": ["sudanese"], "cctld": "sd", "phone": "+249", "langs": ["ar"], "cities": ["khartoum"]},
    "madagascar": {"aliases": ["madagascar"], "demonyms": ["malagasy"], "cctld": "mg", "phone": "+261", "langs": ["fr"], "cities": ["antananarivo"]},
    "mali": {"aliases": ["mali"], "demonyms": ["malian"], "cctld": "ml", "phone": "+223", "langs": ["fr"], "cities": ["bamako"], "ambiguous": True},
    "niger": {"aliases": ["niger"], "demonyms": ["nigerien"], "cctld": "ne", "phone": "+227", "langs": ["fr"], "cities": ["niamey"], "ambiguous": True},
    "chad": {"aliases": ["chad"], "demonyms": ["chadian"], "cctld": "td", "phone": "+235", "langs": ["fr", "ar"], "ambiguous": True},
    "guinea": {"aliases": ["guinea"], "demonyms": ["guinean"], "cctld": "gn", "phone": "+224", "langs": ["fr"], "ambiguous": True},
    "benin": {"aliases": ["benin"], "demonyms": ["beninese"], "cctld": "bj", "phone": "+229", "langs": ["fr"], "ambiguous": True},
    "togo": {"aliases": ["togo"], "demonyms": ["togolese"], "cctld": "tg", "phone": "+228", "langs": ["fr"], "ambiguous": True},
    "libya": {"aliases": ["libya"], "demonyms": ["libyan"], "cctld": "ly", "phone": "+218", "langs": ["ar"], "cities": ["tripoli"]},

    # ---- Europe ---------------------------------------------------------------
    "united kingdom": {"aliases": ["united kingdom", "great britain", "britain", "england", "scotland", "wales", "uk", "gb"],
                       "demonyms": ["british", "english", "scottish", "welsh"], "cctld": "uk", "phone": "+44",
                       "cities": ["london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh", "bristol", "liverpool", "sheffield"]},
    "germany": {"aliases": ["germany", "deutschland"], "demonyms": ["german"], "cctld": "de", "phone": "+49", "langs": ["de"],
                "cities": ["berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart"]},
    "france": {"aliases": ["france"], "demonyms": ["french"], "cctld": "fr", "phone": "+33", "langs": ["fr"],
               "cities": ["paris", "lyon", "marseille", "toulouse", "nice", "nantes"]},
    "italy": {"aliases": ["italy", "italia"], "demonyms": ["italian"], "cctld": "it", "phone": "+39", "langs": ["it"],
              "cities": ["rome", "roma", "milan", "milano", "naples", "turin", "florence"]},
    "spain": {"aliases": ["spain", "españa", "espana"], "demonyms": ["spanish"], "cctld": "es", "phone": "+34", "langs": ["es"],
              "cities": ["madrid", "barcelona", "valencia", "seville", "bilbao"]},
    "netherlands": {"aliases": ["netherlands", "holland", "the netherlands"], "demonyms": ["dutch"], "cctld": "nl", "phone": "+31", "langs": ["nl"],
                    "cities": ["amsterdam", "rotterdam", "the hague", "utrecht", "eindhoven"]},
    "belgium": {"aliases": ["belgium"], "demonyms": ["belgian"], "cctld": "be", "phone": "+32", "langs": ["nl", "fr"],
                "cities": ["brussels", "antwerp", "ghent"]},
    "switzerland": {"aliases": ["switzerland"], "demonyms": ["swiss"], "cctld": "ch", "phone": "+41", "langs": ["de", "fr", "it"],
                    "cities": ["zurich", "geneva", "basel", "bern"]},
    "austria": {"aliases": ["austria"], "demonyms": ["austrian"], "cctld": "at", "phone": "+43", "langs": ["de"],
                "cities": ["vienna", "wien", "graz", "salzburg"]},
    "sweden": {"aliases": ["sweden"], "demonyms": ["swedish"], "cctld": "se", "phone": "+46", "langs": ["sv"],
               "cities": ["stockholm", "gothenburg", "malmö", "malmo"]},
    "norway": {"aliases": ["norway"], "demonyms": ["norwegian"], "cctld": "no", "phone": "+47", "langs": ["no"], "cities": ["oslo", "bergen"]},
    "denmark": {"aliases": ["denmark"], "demonyms": ["danish"], "cctld": "dk", "phone": "+45", "langs": ["da"], "cities": ["copenhagen", "aarhus"]},
    "finland": {"aliases": ["finland"], "demonyms": ["finnish"], "cctld": "fi", "phone": "+358", "langs": ["fi"], "cities": ["helsinki", "espoo", "tampere"]},
    "ireland": {"aliases": ["ireland"], "demonyms": ["irish"], "cctld": "ie", "phone": "+353", "cities": ["dublin", "cork"]},
    "portugal": {"aliases": ["portugal"], "demonyms": ["portuguese"], "cctld": "pt", "phone": "+351", "langs": ["pt"],
                 "cities": ["lisbon", "lisboa", "porto"]},
    "poland": {"aliases": ["poland", "polska"], "demonyms": ["polish"], "cctld": "pl", "phone": "+48", "langs": ["pl"],
               "cities": ["warsaw", "krakow", "kraków", "wroclaw", "gdansk"]},
    "czechia": {"aliases": ["czechia", "czech republic"], "demonyms": ["czech"], "cctld": "cz", "phone": "+420", "langs": ["cs"],
                "cities": ["prague", "praha", "brno"]},
    "slovakia": {"aliases": ["slovakia"], "demonyms": ["slovak"], "cctld": "sk", "phone": "+421", "langs": ["sk"], "cities": ["bratislava"]},
    "hungary": {"aliases": ["hungary"], "demonyms": ["hungarian"], "cctld": "hu", "phone": "+36", "langs": ["hu"], "cities": ["budapest"]},
    "romania": {"aliases": ["romania"], "demonyms": ["romanian"], "cctld": "ro", "phone": "+40", "langs": ["ro"], "cities": ["bucharest", "cluj-napoca"]},
    "bulgaria": {"aliases": ["bulgaria"], "demonyms": ["bulgarian"], "cctld": "bg", "phone": "+359", "langs": ["bg"], "cities": ["sofia", "plovdiv"]},
    "greece": {"aliases": ["greece"], "demonyms": ["greek"], "cctld": "gr", "phone": "+30", "langs": ["el"], "cities": ["athens", "thessaloniki"]},
    "croatia": {"aliases": ["croatia"], "demonyms": ["croatian"], "cctld": "hr", "phone": "+385", "langs": ["hr"], "cities": ["zagreb", "split"]},
    "serbia": {"aliases": ["serbia"], "demonyms": ["serbian"], "cctld": "rs", "phone": "+381", "langs": ["sr"], "cities": ["belgrade", "novi sad"]},
    "slovenia": {"aliases": ["slovenia"], "demonyms": ["slovenian"], "cctld": "si", "phone": "+386", "langs": ["sl"], "cities": ["ljubljana"]},
    "ukraine": {"aliases": ["ukraine"], "demonyms": ["ukrainian"], "cctld": "ua", "phone": "+380", "langs": ["uk"], "cities": ["kyiv", "kiev", "kharkiv", "lviv", "odesa"]},
    "russia": {"aliases": ["russia", "russian federation"], "demonyms": ["russian"], "cctld": "ru", "phone": "+7", "langs": ["ru"],
               "cities": ["moscow", "saint petersburg", "novosibirsk"]},
    "belarus": {"aliases": ["belarus"], "demonyms": ["belarusian"], "cctld": "by", "phone": "+375", "langs": ["ru", "be"], "cities": ["minsk"]},
    "lithuania": {"aliases": ["lithuania"], "demonyms": ["lithuanian"], "cctld": "lt", "phone": "+370", "langs": ["lt"], "cities": ["vilnius", "kaunas"]},
    "latvia": {"aliases": ["latvia"], "demonyms": ["latvian"], "cctld": "lv", "phone": "+371", "langs": ["lv"], "cities": ["riga"]},
    "estonia": {"aliases": ["estonia"], "demonyms": ["estonian"], "cctld": "ee", "phone": "+372", "langs": ["et"], "cities": ["tallinn"]},
    "luxembourg": {"aliases": ["luxembourg"], "demonyms": ["luxembourgish"], "cctld": "lu", "phone": "+352", "langs": ["fr", "de"], "cities": ["luxembourg"]},
    "cyprus": {"aliases": ["cyprus"], "demonyms": ["cypriot"], "cctld": "cy", "phone": "+357", "langs": ["el"], "cities": ["nicosia", "limassol"]},
    "malta": {"aliases": ["malta"], "demonyms": ["maltese"], "cctld": "mt", "phone": "+356", "cities": ["valletta"]},
    "albania": {"aliases": ["albania"], "demonyms": ["albanian"], "cctld": "al", "phone": "+355", "langs": ["sq"], "cities": ["tirana"]},
    "north macedonia": {"aliases": ["north macedonia", "macedonia"], "demonyms": ["macedonian"], "cctld": "mk", "phone": "+389", "langs": ["mk"], "cities": ["skopje"]},
    "bosnia and herzegovina": {"aliases": ["bosnia and herzegovina", "bosnia"], "demonyms": ["bosnian"], "cctld": "ba", "phone": "+387", "langs": ["bs"], "cities": ["sarajevo"]},
    "georgia": {"aliases": ["georgia"], "demonyms": ["georgian"], "cctld": "ge", "phone": "+995", "langs": ["ka"], "cities": ["tbilisi"], "ambiguous": True},
    "azerbaijan": {"aliases": ["azerbaijan"], "demonyms": ["azerbaijani", "azeri"], "cctld": "az", "phone": "+994", "langs": ["az"], "cities": ["baku"]},
    "moldova": {"aliases": ["moldova"], "demonyms": ["moldovan"], "cctld": "md", "phone": "+373", "langs": ["ro", "ru"], "cities": ["chisinau"]},

    # ---- Americas -------------------------------------------------------------
    "united states": {"aliases": ["united states", "united states of america", "usa", "u.s.a.", "u.s.", "america", "us"],
                      "demonyms": ["american"], "cctld": "us", "phone": "+1",
                      "cities": ["new york", "san francisco", "los angeles", "chicago", "boston", "austin", "seattle", "houston", "atlanta"]},
    "canada": {"aliases": ["canada"], "demonyms": ["canadian"], "cctld": "ca", "phone": "+1", "langs": ["fr"],
               "cities": ["toronto", "montreal", "vancouver", "calgary", "ottawa"]},
    "mexico": {"aliases": ["mexico", "méxico"], "demonyms": ["mexican"], "cctld": "mx", "phone": "+52", "langs": ["es"],
               "cities": ["mexico city", "guadalajara", "monterrey", "puebla"]},
    "brazil": {"aliases": ["brazil", "brasil"], "demonyms": ["brazilian"], "cctld": "br", "phone": "+55", "langs": ["pt"],
               "cities": ["são paulo", "sao paulo", "rio de janeiro", "brasília", "brasilia", "belo horizonte"]},
    "argentina": {"aliases": ["argentina"], "demonyms": ["argentine", "argentinian"], "cctld": "ar", "phone": "+54", "langs": ["es"],
                  "cities": ["buenos aires", "córdoba", "cordoba", "rosario"]},
    "chile": {"aliases": ["chile"], "demonyms": ["chilean"], "cctld": "cl", "phone": "+56", "langs": ["es"], "cities": ["santiago", "valparaíso"], "ambiguous": True},
    "colombia": {"aliases": ["colombia"], "demonyms": ["colombian"], "cctld": "co", "phone": "+57", "langs": ["es"], "cities": ["bogotá", "bogota", "medellín", "medellin", "cali"]},
    "peru": {"aliases": ["peru", "perú"], "demonyms": ["peruvian"], "cctld": "pe", "phone": "+51", "langs": ["es"], "cities": ["lima"]},
    "venezuela": {"aliases": ["venezuela"], "demonyms": ["venezuelan"], "cctld": "ve", "phone": "+58", "langs": ["es"], "cities": ["caracas"]},
    "ecuador": {"aliases": ["ecuador"], "demonyms": ["ecuadorian"], "cctld": "ec", "phone": "+593", "langs": ["es"], "cities": ["quito", "guayaquil"]},
    "uruguay": {"aliases": ["uruguay"], "demonyms": ["uruguayan"], "cctld": "uy", "phone": "+598", "langs": ["es"], "cities": ["montevideo"]},
    "paraguay": {"aliases": ["paraguay"], "demonyms": ["paraguayan"], "cctld": "py", "phone": "+595", "langs": ["es"], "cities": ["asunción", "asuncion"]},
    "bolivia": {"aliases": ["bolivia"], "demonyms": ["bolivian"], "cctld": "bo", "phone": "+591", "langs": ["es"], "cities": ["la paz", "santa cruz"]},
    "guatemala": {"aliases": ["guatemala"], "demonyms": ["guatemalan"], "cctld": "gt", "phone": "+502", "langs": ["es"], "cities": ["guatemala city"]},
    "costa rica": {"aliases": ["costa rica"], "demonyms": ["costa rican"], "cctld": "cr", "phone": "+506", "langs": ["es"], "cities": ["san josé", "san jose"]},
    "panama": {"aliases": ["panama", "panamá"], "demonyms": ["panamanian"], "cctld": "pa", "phone": "+507", "langs": ["es"], "cities": ["panama city"]},

    # ---- Oceania --------------------------------------------------------------
    "australia": {"aliases": ["australia"], "demonyms": ["australian"], "cctld": "au", "phone": "+61",
                  "cities": ["sydney", "melbourne", "brisbane", "perth", "adelaide"]},
    "new zealand": {"aliases": ["new zealand"], "demonyms": ["new zealander", "kiwi"], "cctld": "nz", "phone": "+64",
                    "cities": ["auckland", "wellington", "christchurch"]},
}
