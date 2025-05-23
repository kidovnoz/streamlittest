import streamlit as st
from ultralytics import YOLO
from PIL import Image
import numpy as np
import yaml
import sys
import asyncio
import torch
import cv2
import torchvision

# Cài đặt tương thích với Windows và Python >= 3.8
if sys.platform.startswith('win') and sys.version_info >= (3, 8):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.title("AOI-AI Meiko Automation")

# Kiểm tra GPU
st.sidebar.markdown("### 🧠 GPU Info")
st.sidebar.write("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    st.sidebar.write("GPU:", torch.cuda.get_device_name(0))
else:
    st.sidebar.warning("⚠️ Không tìm thấy GPU, đang chạy trên CPU.")

# Load file YAML cấu hình model
def load_model_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    model_paths = [model["weight_path"] for model in config["models"]]
    model_names = [model["class_name"] for model in config["models"]]
    return model_paths, model_names

yaml_path = "config.yaml"
st.logo("meiko-logo.webp", size="large", link="https://meiko-elec.com.vn/")

# Sidebar settings
st.sidebar.header("⚙️ Cấu hình")
confidence = st.sidebar.slider("Ngưỡng confidence", 0.1, 1.0, 0.25, 0.05)

# Nút xoá cache ảnh
if st.sidebar.button("🧹 Xử lý lại"):
    st.session_state.processed_images = {}
    st.sidebar.success("Đã xóa cache.")
# Mật khẩu admin
ADMIN_PASSWORD = "1234"
st.sidebar.title("🔒 Đăng nhập quản trị")
password_input = st.sidebar.text_input("🔑 Nhập mật khẩu", type="password")

if password_input == ADMIN_PASSWORD:
    st.sidebar.success("✅ Đăng nhập thành công!")
    yaml_path = st.sidebar.text_input(" 🔧 Đường dẫn file YAML", value=yaml_path)
    model_paths, model_names = load_model_config(yaml_path)
    
else:
    st.sidebar.warning("🔐 Nhập mật khẩu để xem cấu hình")
    model_paths, model_names = load_model_config(yaml_path)

# ✅ Load model chỉ 1 lần
@st.cache_resource
def load_models(paths):
    return [YOLO(path) for path in paths]

models = load_models(model_paths)

# Lưu kết quả đã xử lý vào session_state
if "processed_images" not in st.session_state:
    st.session_state.processed_images = {}

# Xử lý ảnh đầu vào
def process_image(image_file, models, model_names, confidence):
    try:
        image = Image.open(image_file).convert("RGB")
        image_array = np.array(image)

        all_boxes = []

        for i, model in enumerate(models):
            try:
                model.eval()
                results = model.predict(
                    source=image,
                    conf=confidence,
                    imgsz=640,
                    device='cpu',
                    augment=True
                )

                for r in results:
                    if r.boxes is not None and len(r.boxes) > 0:
                        for box in r.boxes:
                            x1, y1, x2, y2 = map(float, box.xyxy[0].tolist())
                            conf_score = float(box.conf.item())
                            cls = int(box.cls.item())
                            
                            all_boxes.append({
                                "box": [x1, y1, x2, y2],
                                "conf": conf_score,
                                "model_idx": i,
                                "labels": [f"{cls}: {conf_score:.2f}"]
                            })


            except Exception as e:
                st.error(f"Lỗi predict model {i}: {e}")

        # Nếu không có box nào được detect
        if not all_boxes:
            return {
                "image_id": image_file.name,
                "image_show": image,
                "found": False,
                "label": "Không phát hiện"
            }

        # Tạo tensor để chạy NMS
        boxes_tensor = torch.tensor([b["box"] for b in all_boxes], dtype=torch.float32)
        confs_tensor = torch.tensor([b["conf"] for b in all_boxes], dtype=torch.float32)

        # Chạy Non-Maximum Suppression
        keep_idxs = torchvision.ops.nms(boxes_tensor, confs_tensor, iou_threshold=0.1)

        # Lấy các box được giữ lại
        final_boxes = [all_boxes[i] for i in keep_idxs.tolist()]
        final_boxes = sorted(final_boxes, key=lambda x: x["conf"], reverse=True)

        # Vẽ kết quả lên ảnh gốc
        draw_img = image_array.copy()
        for b in final_boxes:
            x1, y1, x2, y2 = map(int, b["box"])
            label = f"{model_names[b['model_idx']]}: {b['conf']:.2f}"
            cv2.rectangle(draw_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(draw_img, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

        final_image = Image.fromarray(draw_img)

        return {
            "image_id": image_file.name,
            "image_show": final_image,
            "found": True,
            "label": f"{len(final_boxes)} vùng lỗi"
        }

    except Exception as e:
        st.error(f"Lỗi xử lý ảnh: {e}")
        return {
            "image_id": image_file.name,
            "image_show": None,
            "found": False,
            "label": "Lỗi xử lý"
        }

# Upload nhiều ảnh
uploaded_files = st.file_uploader("📁 Chọn ảnh đầu vào", type=["jpg", "jpeg", "png", "bmp"], accept_multiple_files=True)
num_cols = 1

if uploaded_files:
    st.markdown("## 📊 Kết quả phát hiện")
    cols = st.columns(num_cols)

    for idx, file in enumerate(uploaded_files):
        image_key = file.name

        # Kiểm tra nếu ảnh đã xử lý
        if image_key in st.session_state.processed_images:
            result = st.session_state.processed_images[image_key]
        else:
            result = process_image(file, models, model_names, confidence)
            st.session_state.processed_images[image_key] = result

        col = cols[idx % num_cols]
        with col:
                st.markdown(f"**Ảnh {idx+1}**")

                # Hiển thị ảnh
                if result["image_show"] is not None:
                    st.image(result["image_show"], use_container_width=True, output_format="auto")

                # Hiển thị label với chiều cao cố định, ellipsis nếu quá dài
                st.markdown(
                    f"""
                    <div style='height: 15px; 
                                display: flex; 
                                align-items: center; 
                                justify-content: center; 
                                text-align: center; 
                                font-size: 12px;
                                font-weight: bold;
                                overflow: hidden;
                                text-overflow: ellipsis;
                                white-space: nowrap;'>
                        {result['label']}
                    </div>
                    """, 
                    unsafe_allow_html=True
                )

                # Hiển thị icon ✅/❌ ở dòng riêng, luôn nằm dưới
                st.markdown(
                    f"<div style='text-align: center; font-size: 24px;'>{'✅' if result['found'] else '❌'}</div>", 
                    unsafe_allow_html=True
                )



        if (idx + 1) % num_cols == 0 and idx + 1 != len(uploaded_files):
            cols = st.columns(num_cols)

    # Bổ sung cột trống nếu số ảnh không chia hết
    remainder = len(uploaded_files) % num_cols
    if remainder != 0:
        for _ in range(num_cols - remainder):
            with st.columns(1)[0]:
                st.empty()
