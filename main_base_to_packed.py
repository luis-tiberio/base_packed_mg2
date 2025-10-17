import asyncio
from playwright.async_api import async_playwright
import time
import datetime
import os
import shutil
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import zipfile
from gspread_dataframe import set_with_dataframe # Import para upload de DataFrame

DOWNLOAD_DIR = "/tmp/shopee_automation"
ops_id = os.environ.get('OPS_ID')
ops_senha = os.environ.get('OPS_SENHA')

def rename_downloaded_file(download_dir, download_path):
    """Renames the downloaded file to include the current hour."""
    try:
        current_hour = datetime.datetime.now().strftime("%H")
        new_file_name = f"TO-Packed{current_hour}.zip"
        new_file_path = os.path.join(download_dir, new_file_name)
        if os.path.exists(new_file_path):
            os.remove(new_file_path)
        shutil.move(download_path, new_file_path)
        print(f"Arquivo salvo como: {new_file_path}")
        return new_file_path
    except Exception as e:
        print(f"Erro ao renomear o arquivo: {e}")
        return None

def unzip_and_process_data(zip_path, extract_to_dir):
    """
    Unzips a file, merges all CSVs, and processes the data according to the specified logic.
    
    Args:
        zip_path (str): The full path to the .zip file.
        extract_to_dir (str): The directory to extract files to.

    Returns:
        pd.DataFrame: A fully processed pandas DataFrame, or None if an error occurs.
    """
    try:
        unzip_folder = os.path.join(extract_to_dir, "extracted_files")
        os.makedirs(unzip_folder, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_folder)
        print(f"Arquivo '{os.path.basename(zip_path)}' descompactado.")

        csv_files = [os.path.join(unzip_folder, f) for f in os.listdir(unzip_folder) if f.lower().endswith('.csv')]
        
        if not csv_files:
            print("Nenhum arquivo CSV encontrado no ZIP.")
            shutil.rmtree(unzip_folder)
            return None

        print(f"Lendo e unificando {len(csv_files)} arquivos CSV...")
        all_dfs = [pd.read_csv(file, encoding='utf-8') for file in csv_files]
        df_final = pd.concat(all_dfs, ignore_index=True)

        # === INÍCIO DA LÓGICA DE PROCESSAMENTO INTEGRADA ===
        print("Iniciando processamento dos dados...")
        
        # 1. Selecionar colunas desejadas pela posição
        colunas_desejadas = [0, 9, 15, 17, 2, 23]
        df_selecionado = df_final.iloc[:, colunas_desejadas].copy()
        
        # 2. Renomear colunas
        df_selecionado.columns = ['Chave', 'Coluna9', 'Coluna15', 'Coluna17', 'Coluna2', 'Coluna23']

        # 3. Contar ocorrências da 'Chave'
        contagem = df_selecionado['Chave'].value_counts().reset_index()
        contagem.columns = ['Chave', 'Quantidade']

        # 4. Agrupar para obter valores únicos e evitar duplicatas
        agrupado = df_selecionado.groupby('Chave').agg({
            'Coluna9': 'first',
            'Coluna15': 'first',
            'Coluna17': 'first',
            'Coluna2': 'first',
            'Coluna23': 'first',
        }).reset_index()

        # 5. Juntar os dados agrupados com a contagem
        resultado = pd.merge(agrupado, contagem, on='Chave')
        
        # 6. Reordenar colunas para o resultado final
        resultado = resultado[['Chave', 'Coluna9', 'Coluna15', 'Coluna17', 'Quantidade', 'Coluna2', 'Coluna23']]
        
        print("Processamento de dados concluído com sucesso.")
        # === FIM DA LÓGICA DE PROCESSAMENTO ===
        
        shutil.rmtree(unzip_folder) # Limpa a pasta com os arquivos extraídos
        
        return resultado
        
    except Exception as e:
        print(f"Erro ao descompactar ou processar os dados: {e}")
        return None


def update_google_sheet_with_dataframe(df_to_upload):
    """Updates a Google Sheet with the content of a pandas DataFrame."""
    if df_to_upload is None or df_to_upload.empty:
        print("Nenhum dado para enviar ao Google Sheets.")
        return
        
    try:
        print("Enviando dados processados para o Google Sheets...")
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive"]
        # ATENÇÃO: Use o caminho correto para seu arquivo de credenciais JSON
        creds = ServiceAccountCredentials.from_json_keyfile_name("hxh.json", scope)
        client = gspread.authorize(creds)
        
        # ATENÇÃO: Use o nome correto da sua planilha e da aba
        planilha = client.open("Stage Out Management - MG2 - SPX")
        aba = planilha.worksheet("Packed")
        
        aba.clear() # Limpa a aba antes de inserir novos dados
        set_with_dataframe(aba, df_to_upload) # Usa a função para enviar o DataFrame
        
        print("✅ Dados enviados para o Google Sheets com sucesso!")
        time.sleep(5)

    except Exception as e:
        print(f"❌ Erro ao enviar para o Google Sheets: {e}")

async def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1920,1080"])
        context = await browser.new_context(accept_downloads=True, viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        try:
            # LOGIN
            await page.goto("https://spx.shopee.com.br/")
            await page.wait_for_selector('xpath=//*[@placeholder="Ops ID"]', timeout=15000)
            await page.locator('xpath=//*[@placeholder="Ops ID"]').fill(ops_id)
            await page.locator('xpath=//*[@placeholder="Senha"]').fill(ops_senha)
            await page.locator('xpath=/html/body/div[1]/div/div[2]/div/div/div[1]/div[3]/form/div/div/button').click()
            await page.wait_for_timeout(15000)
            try:
                await page.locator('.ssc-dialog-close').click(timeout=5000)
            except:
                print("Nenhum pop-up de diálogo foi encontrado.")
                await page.keyboard.press("Escape")
            
              # NAVEGAÇÃO E DOWNLOAD
            await page.goto("https://spx.shopee.com.br/#/general-to-management")
            await page.wait_for_timeout(15000)
            await page.get_by_role('button', name='Exportar').click()
            await page.wait_for_timeout(8000)
            await page.locator('xpath=/html[1]/body[1]/span[4]/div[1]/div[1]/div[1]').click()
            await page.wait_for_timeout(8000)
            await page.get_by_role("treeitem", name="Packed", exact=True).click()
            await page.wait_for_timeout(8000)
            await page.get_by_role("button", name="Confirmar").click()
            await page.wait_for_timeout(150000)
            
            # DOWNLOAD
            async with page.expect_download() as download_info:
                await page.get_by_role("button", name="Baixar").first.click()
            
            download = await download_info.value
            download_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
            await download.save_as(download_path)
            print(f"Download concluído: {download_path}")

            # --- FLUXO DE PROCESSAMENTO E UPLOAD ---
            renamed_zip_path = rename_downloaded_file(DOWNLOAD_DIR, download_path)
            
            if renamed_zip_path:
                # 1. Descompacta e processa os dados em memória, retornando um DataFrame
                final_dataframe = unzip_and_process_data(renamed_zip_path, DOWNLOAD_DIR)
                
                # 2. Faz o upload do DataFrame final para o Google Sheets
                update_google_sheet_with_dataframe(final_dataframe)

        except Exception as e:
            print(f"Erro durante o processo principal: {e}")
        finally:
            await browser.close()
            if os.path.exists(DOWNLOAD_DIR):
                shutil.rmtree(DOWNLOAD_DIR)
                print(f"Diretório de trabalho '{DOWNLOAD_DIR}' limpo.")

if __name__ == "__main__":
    asyncio.run(main())
