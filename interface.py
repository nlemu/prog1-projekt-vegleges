import pandas as pd
import os
import math
import time
import streamlit as st
import csv
from datetime import datetime
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import mpu
from io import BytesIO
import requests
import locale


# az alapjátékhoz szükséges függvény
def jatek(tipp, coordinates, gepgondolata):
    """Inputként megkapja a játékos által tippelt várost,
    ha nem egyezik meg a gép gondolatával, akkor visszaadja, hogy milyen irányba és milyen távolságra található tőle.
    Ha megegyezik a gép gondolata a tippelt várossal, akkor egy space-t (" ") ad visszatérési értékként, amivel vége a játéknak/adott körnek.
    """

    if gepgondolata == tipp:
        return "    "
    elif tipp not in coordinates["Város"].values:
        return "Sajnos a tippelt város nem szerepel az adatbázisomban. Ügyelj arra, hogy a településnevet nagybetűvel kezdve, ékezettel írd le!"
        # teszteléseim alapján nincs erre szükség, mert legördülő listából nem is enged mást választani, de a streamlit tud annyira szeszélyes lenni, hogy inkább bennehagyom
        # (azt feltételezve, hogy mégis lehet valahogyan nem értelmes inputot leadni tippként), nehogy ennek hiánya okozzon gondot a futásnál
    else:
        gep_lat = coordinates.loc[
            coordinates["Város"] == gepgondolata, "latitude"
        ].values[0]
        gep_long = coordinates.loc[
            coordinates["Város"] == gepgondolata, "longitude"
        ].values[0]
        tipp_lat = coordinates.loc[coordinates["Város"] == tipp, "latitude"].values[0]
        tipp_long = coordinates.loc[coordinates["Város"] == tipp, "longitude"].values[0]

        lat_km = 111.574
        long_km = 111.320 * math.cos(math.radians((gep_lat + tipp_lat) / 2))

        dif_lat = abs(gep_lat - tipp_lat) * lat_km
        dif_long = abs(gep_long - tipp_long) * long_km

        distance = mpu.haversine_distance((gep_lat, gep_long), (tipp_lat, tipp_long))
        # kicsit necces, hogy a pontos távolság Haversine formulával van számolva, viszont az, hogy mennyire van délre/északra/keletre/nyugatra dolgok meg laposföldhöz van viszonyítva

        eszakdel = "" if dif_lat < 3 else ("észak" if gep_lat > tipp_lat else "dél")
        nyugatkelet = (
            "" if dif_long < 3 else ("kelet" if gep_long > tipp_long else "nyugat")
        )
        # ha az észak/dél/nyugat/kelet távolság kisebb, mint 3km, akkor azt nem írja ki (így pl. csak annyit ír, hogy "4,6km-re nyugatra")

        if dif_lat < 3 and dif_long < 3:
            return f"A gép által kigondolt város {tipp} településhez viszonyítva {round(distance, 2)} km-re található."
        # ha az észak/dél és nyugat/kelet is 3km-en belül van, akkor egyiket se írja ki, csak a konkrét távolságot

        return f"A gép által kigondolt város {tipp} településhez viszonyítva {round(distance, 2)} km-re {eszakdel}{nyugatkelet} irányba található."


# Ez kell ahhoz, hogy miután valaki kitalált a gép gondolatát, ábrázolni lehessen a tippjeit egy Balcsi térképen
def terkep():
    """Egy dictionaryben eltárolásra kerül a tipp leadásakor a város neve és koordinátái.
    A függvény ezeket a városokat felrakja a Balaton köré egy ponttal és a nevüket kiírva.
    """

    # innentől ameddig jelezve van (kb. 65. sor) a terkep része chat gpt-nek köszönhető teljesen
    extent = [17.18, 18.4, 46.66, 47.1]  # [min_lon, max_lon, min_lat, max_lat]
    fig, ax = plt.subplots(
        figsize=(8, 8), subplot_kw={"projection": ccrs.PlateCarree()}
    )
    ax.set_extent(extent)
    ax.add_feature(cfeature.BORDERS, linestyle=":")
    ax.add_feature(cfeature.COASTLINE)
    ax.add_feature(cfeature.LAND, edgecolor="black")
    ax.add_feature(cfeature.LAKES, color="blue")
    # idáig --> magamtól sablont nem találtam, nem tudtam megcsinálni és nem jöttem rá hogyan lehet így leszedni, hogy azzal tudjak tovább dolgozni (tehát lehessen longitude és latitude által pluszban pontokat elhelyezni a térképen és látszódjon hol van a Balaton)

    for város, koordináták in st.session_state.tippelt_varos_dict.items():
        longitude = koordináták["longitude"]
        latitude = koordináták["latitude"]
        ax.scatter(longitude, latitude, color="red", s=50, zorder=10)
        ax.text(longitude + 0.015, latitude - 0.02, város, fontsize=8)

    plt.title("Így jutottál el a célig :))", fontsize=10)
    st.pyplot(fig)


# Játék típusának kiválasztása (egyszerű vagy kompetitív)
def jatek_tipus_valasztas():
    """A játék legelején a játékos választhat, hogy egyszerű (1 körös) vagy kompetitív (3 körös, aggregált eredménnyel) játékot szeretne játszani.
    A függvény a választási lehetőséget biztosítja.
    """

    if "típus" not in st.session_state:
        st.session_state.típus = None

    if st.session_state.típus is None:
        col1, col2 = st.columns(2)

        if col1.button("Egyszerű játék"):
            st.session_state.típus = "egyszerű"
            st.session_state.jatekvalasztofelirat_allapot = False

        if col2.button("Kompetitív játék"):
            st.session_state.típus = "kompetitív"
            st.session_state.jatekvalasztofelirat_allapot = False


# új játék indítása függvény --> nem tökéletesen jelenik meg és általában kétszer kell kattintani, de nem tudom hogyan lehetne kijavítani
def új_játék_indítása():
    """Új játék indításához a session state-ben tárolt dolgokat kitörli"""
    
    st.session_state.clear()
    jatek_tipus_valasztas()


def ranglistahoz(
    Játékosnév, total_time, total_tipp_szam, start_time, pontos_start_time
):
    """Kompetitív játék esetében miután három egymás utáni körben is kitalálta a "gondolt" balatoni települést, bekerül az eredménye a ranglistába (csv fájlba)."""

    fajl_nev = "ranglista6.csv"

    letezik = os.path.isfile(fajl_nev)

    with open(fajl_nev, mode="a", newline="", encoding="utf-8") as csvfile:
        csvwriter = csv.writer(csvfile)

        if not letezik:
            csvwriter.writerow(
                [
                    "Játékosnév",
                    "Össz. idő (mp)",
                    "Össz. tipp szám",
                    "start_time",
                    "Mikor játszott",
                ]
            )  # első sor --> változók nevei

        csvwriter.writerow(
            [Játékosnév, total_time, total_tipp_szam, start_time, pontos_start_time]
        )


def ranglista_meghivasa(file_neve):
    """A ranglistaként eltárolt csv fájl meghívását segítő függvény."""

    return pd.read_csv(file_neve)


def egyszeru_jatek(coordinates):
    """Az egyszerű játékhoz szükséges függvény. Miután a játékos eltalálta, hogy melyik településre gondolt a gép, kiírja, hogy mennyi időre és hány tippre volt szüksége a játékosnak ehhez.
    Továbbá meghívja a Balaton térképet, amelyen ábrázolva vannak a tippelt városok elhelyezkedése.
    """

    if "tippelt_varos_dict" not in st.session_state:
        st.session_state.tippelt_varos_dict = {}

    if st.session_state.típus == "egyszerű":
        if "gepgondolata" not in st.session_state:
            st.session_state.gepgondolata = coordinates.sample(1).iloc[0]["Város"]
            st.session_state.tipp_szam = 0
            st.session_state.start_time = time.time()

        # locale.setlocale(locale.LC_COLLATE, "hu_HU.UTF-8")
        # streamlit ezt nem szereti
        
        # helyette applikációhoz:
        locale.setlocale(locale.LC_COLLATE, "")
        tipp = st.selectbox(
            label="Válaszd ki a tipped a legördülő listából!",
            options=sorted(coordinates["Város"].tolist(), key=locale.strxfrm),
        )

        if st.button("Küldés") and tipp:

            # a tippelt_varos_dict a balcsis ábrázoláshoz kell:
            index = coordinates[coordinates["Város"] == tipp].iloc[0]
            latitude = index["latitude"]
            longitude = index["longitude"]
            st.session_state.tippelt_varos_dict[tipp] = {
                "latitude": latitude,
                "longitude": longitude,
            }

            st.session_state.tipp_szam += 1
            eredmeny = jatek(tipp, coordinates, st.session_state.gepgondolata)
            st.write(eredmeny)

            if eredmeny == "    ":
                eltelt_ido = time.time() - st.session_state.start_time
                perc = int(eltelt_ido // 60)
                masodperc = int(eltelt_ido % 60)
                st.success(
                    f"Gratulálok, nyertél! Ehhez {st.session_state.tipp_szam} tippre és {perc} perc {masodperc} mp-re volt szükséged! :))"
                )
                st.balloons()
                terkep()

    if st.button("Új játék indítása (2x kattintsd)"):
        új_játék_indítása()
        # ezek a gombok nem működnek tökéletesen, általában kétszer kell kattintani, nem tudom, hogyan lehetne javítani


def kompetitiv_jatek(coordinates):
    """A kompetitív játékmódhoz szükséges függvény.
    A játék az egyszerű játékhoz hasonlóan van lejátszva, egymás után háromszor. A gép minden kör elején gondol egy településre, amelyet ki kell találnia a játékosnak.
    Miután egy adott körben kitalálja a játékos a gondolt települést, a gép visszaadja, hogy ehhez mennyi időre és hány tippre volt szükség, illetve meghívja a tippjeit elhelyező térképet.
    A játékosnak egymás után három körben is ki kell találnia a gép gondolatát. Miután ezt háromszor is megtette, a függvény visszaadja, hogy aggregálva mennyi időre és hány tippre volt szüksége.
    A tipp szám és az idő alapján is felkerül a ranglistára. Az idő alapján a TOP10 játékosnak az eredménye megjelenik egy ranglistán.
    """

    if st.session_state.típus == "kompetitív":

        # innentől
        if "kovetkezo_kor" not in st.session_state:
            st.session_state.kovetkezo_kor = False
        if "Játékosnév" not in st.session_state:
            st.session_state.Játékosnév = None
        if "jatek_indul" not in st.session_state:
            st.session_state.jatek_indul = False
        if "kompetitív_round" not in st.session_state:
            st.session_state.kompetitív_round = 1
        if "total_tipp_szam" not in st.session_state:
            st.session_state.total_tipp_szam = 0
        if "total_time" not in st.session_state:
            st.session_state.total_time = 0
        if "round_tipp_szam" not in st.session_state:
            st.session_state.round_tipp_szam = 0
        if "start_time" not in st.session_state:
            st.session_state.start_time = time.time()
        if "tippelt_varos_dict" not in st.session_state:
            st.session_state.tippelt_varos_dict = {}

        if not st.session_state.jatek_indul:
            st.session_state.Játékosnév = st.text_input("Add meg a játékosneved:")

            if st.button("Kezdjük"):
                if st.session_state.Játékosnév.strip() == "":
                    st.error("Adj meg egy érvényes játékosnevet!")
                    st.session_state.Játékosnév = None
                else:
                    st.success(
                        f"Sok sikert, {st.session_state.Játékosnév}! Kezdődik a játék!"
                    )
                    st.session_state.jatek_indul = True

        if st.session_state.jatek_indul == True:

            # ez a rész biztosítja a 2. és 3. kört
            if st.session_state.kovetkezo_kor == True:

                st.session_state.kompetitív_round += 1
                st.session_state.gepgondolata = coordinates.sample(1).iloc[0]["Város"]
                st.session_state.round_tipp_szam = 0
                st.session_state.round_start_time = time.time()
                st.session_state.kovetkezo_kor = False

            # ez az első körhöz kell a kompetitív játékban
            if "gepgondolata" not in st.session_state:
                st.session_state.gepgondolata = coordinates.sample(1).iloc[0]["Város"]
                st.session_state.round_tipp_szam = 0
                st.session_state.round_start_time = time.time()

            
            # locale.setlocale(locale.LC_COLLATE, "hu_HU.UTF-8")
            # streamlit ezt nem szereti
        
            # helyette applikációhoz:
            locale.setlocale(locale.LC_COLLATE, "")
            tipp = st.selectbox(
                label="Válaszd ki a tipped a legördülő listából!",
                options=sorted(coordinates["Város"].tolist(), key=locale.strxfrm),
            )

            if st.button("Küldés") and tipp:

                # a tippelt_varos_dict a balcsis ábrázoláshoz kell:
                index = coordinates[coordinates["Város"] == tipp].iloc[0]
                latitude = index["latitude"]
                longitude = index["longitude"]
                st.session_state.tippelt_varos_dict[tipp] = {
                    "latitude": latitude,
                    "longitude": longitude,
                }

                st.session_state.round_tipp_szam += 1
                eredmeny = jatek(tipp, coordinates, st.session_state.gepgondolata)
                st.write(eredmeny)

                if eredmeny == "    ":
                    round_time = time.time() - st.session_state.round_start_time
                    st.session_state.total_tipp_szam += st.session_state.round_tipp_szam
                    st.session_state.total_time += round_time
                    perc = int(round_time // 60)
                    masodperc = int(round_time % 60)

                    st.write(
                        f"Gratulálok, {st.session_state.Játékosnév}! A(z) {st.session_state.kompetitív_round}. kör sikeres volt! {st.session_state.round_tipp_szam} tippre és {perc} perc {masodperc} másodpercre volt szükséged."
                    )

                    terkep()
                    st.session_state.tippelt_varos_dict = {}
                    # itt ezt ki kell "üríteni", hogy az új "kör"-nél csak az új tipphez tartozó városok legyenek eltárolva a dictionaryben és ábrázolva a térképen

                    if st.session_state.kompetitív_round < 3:
                        st.session_state.kovetkezo_kor = True  # 3. kör után ez már nem fut le, így nincs visszaállítva, így nem kezdődik új kör
                        st.success(
                            "Egyelőre nincs sok idő örömködni. Vajon ezúttal mire gondolt a gép? Válaszd ki a fenti legördülő listából, aztán kattints a Küldés gombra! \n\nAmint leadod a következő kör első tippjét, újra el is indul a számláló."
                        )

                    else:
                        ranglistahoz(
                            Játékosnév=st.session_state.Játékosnév,
                            total_time=st.session_state.total_time,
                            total_tipp_szam=st.session_state.total_tipp_szam,
                            start_time=st.session_state.start_time,
                            pontos_start_time=datetime.fromtimestamp(
                                round(st.session_state.start_time)
                            ),
                        )  # eltárolok minden eredményt egy csv file-ban

                        total_time_perc = int(st.session_state.total_time // 60)
                        total_time_masodperc = int(st.session_state.total_time % 60)

                        ranglista = ranglista_meghivasa("ranglista6.csv")

                        ranglista_time = ranglista.sort_values(
                            ["Össz. idő (mp)", "Össz. tipp szám"]
                        ).reset_index()
                        helyezes_time = (
                            ranglista_time[
                                ranglista_time["start_time"]
                                == st.session_state.start_time
                            ].index[0]
                            + 1
                        )  # a start_time-ot használom kb. ID-ként (ez az, ami egyedi)

                        ranglista_tipp = ranglista.sort_values(
                            ["Össz. tipp szám", "Össz. idő (mp)"]
                        ).reset_index()
                        helyezes_tipp = (
                            ranglista_tipp[
                                ranglista_tipp["start_time"]
                                == st.session_state.start_time
                            ].index[0]
                            + 1
                        )

                        st.success(
                            f"A 3 kör teljesítéséhez összesen {st.session_state.total_tipp_szam} tippre és {total_time_perc} perc {total_time_masodperc} másodpercre volt szükséged. Ezzel a ranglista {helyezes_tipp}. helyére kerültél tipp szám és a(z) {helyezes_time}. helyére idő alapján."
                        )
                        st.balloons()

                        ranglista = ranglista.sort_values(
                            ["Össz. idő (mp)", "Össz. tipp szám"]
                        ).reset_index()

                        st.write("A TOP10 leggyorsabb ranglistája így néz ki jelenleg:")
                        st.dataframe(
                            ranglista.head(n=10),
                            hide_index=True,
                            column_order=(
                                "Játékosnév",
                                "Össz. idő (mp)",
                                "Össz. tipp szám",
                                "Mikor játszott",
                            ),
                        )

    if st.button("Új játék indítása (2x kattintsd)"):
        új_játék_indítása()


def main():
    """A kiinduló állapot meghívásához szükséges függvény. A fájl lefuttatásakor ez van meghívva. Az alap userface megjelenítését segíti."""

    st.title("Neked a tenger a Balaton?")

    if "jatekvalasztofelirat" not in st.session_state:
        st.session_state.jatekvalasztofelirat = (
            "Egyszerű játékot szeretnél vagy kompetitív alkat vagy?"
        )
    if "jatekvalasztofelirat_allapot" not in st.session_state:
        st.session_state.jatekvalasztofelirat_allapot = True
    if st.session_state.jatekvalasztofelirat_allapot == True:
        st.write(
            "Egyszerű játékot szeretnél vagy kompetitív alkat vagy? \n\n Az egyszerű játék során ki kell találnod, hogy vajon melyik balatonparti településre gondolt a gépállat. \n\nA kompetitív játék során ezt a művelet kell megismételned háromszor és, ha elég gyors vagy és jól ismered a Riviérát, akár a ranglistára is felkerülhetsz! \n\nHajrá!!! :))"
        )
        # ezt biztos lehet szebben is, de így működik az, hogy csak akkor írja ki, amikor valóban ki kell írni

    url_data = "https://raw.githubusercontent.com/nlemu/prog1-projekt-vegleges/main/coordinates.xlsx"
    response = requests.get(url_data)
    coordinates = pd.read_excel(BytesIO(response.content))

    jatek_tipus_valasztas()

    if st.session_state.típus == "egyszerű":
        egyszeru_jatek(coordinates)

    if st.session_state.típus == "kompetitív":
        kompetitiv_jatek(coordinates)


if __name__ == "__main__":
    """A fájl lefuttatásakor csak ez fut le automatikusan, ez hívja meg a main függvényt, ami a játék elindításához kell.
    """

    main()
